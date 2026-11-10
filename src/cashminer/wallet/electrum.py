"""Tiny TLS Electrum Cash client for the *wallet only*.

Observations from any Electrum server are hints, not independently verified chain
consensus. TLS verifies certificates; genesis and BCH fork checkpoint are pinned
where available to prevent connecting to an unrelated BTC network by mistake.
"""
from __future__ import annotations
import hashlib
import hmac
import re
import json
import socket
import ssl
import time
from collections import deque
from cashminer.wallet.crypto import sha256d

NETWORK_GENESIS = {
    'mainnet': '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f',
    'testnet3': '000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943',
    'testnet4': '000000001dd410c49a788668ce26751718cc797474d3152a5fc073dd44fd9f7b',
    'chipnet': '000000001dd410c49a788668ce26751718cc797474d3152a5fc073dd44fd9f7b',
}
BCH_FORK_CHECKPOINT = ('mainnet', 478559,
    '000000000000000000651ef99cb9fcbe0dadde1d424bd9f15ff20136191a5eec')
# BCHN chainparams.cpp checkpoint, well after Chipnet split from Testnet4.
CHIPNET_CHECKPOINT = (325627, '000000002bb8a32bd6b1022e5370b10e7dc139770d626e1a0911e6b596cf3069')
TESTNET4_CHECKPOINT = (325709, '00000000000097a6ca206aa88b45a2158eea1a9ab8a49aed8f4b193d558e74b4')
NETWORK_POSTFORK_CHECKPOINTS = {'chipnet': CHIPNET_CHECKPOINT, 'testnet4': TESTNET4_CHECKPOINT}
DEFAULT_SERVERS = {
    'mainnet': [('electroncash.dk', 50002), ('bch.imaginary.cash', 50002),
                ('bch.loping.net', 50002)],
    # Testnet3: comprobados contra genesis Testnet3 en 2026-11-08.
    # bch0.kister.net:51002 es alternativo (certificado autofirmado).
    'testnet3': [('testnet.imaginary.cash', 50002),
                 ('tbch.loping.net', 60002), ('blackie.c3-soft.com', 60002)],
    # BCH Testnet4, SSL/TLS Electrum (not Bitcoin BTC Testnet4).
    'testnet4': [('tbch4.loping.net', 62002), ('blackie.c3-soft.com', 62002),
                 ('testnet4.imaginary.cash', 62002)],
    'chipnet': [('chipnet.bch.ninja', 50002), ('chipnet.imaginary.cash', 50002),
                ('chipnet.c3-soft.com', 64002)],
    'tempnet_fablous_2026': [],
    'regtest': [],
}
TESTNET3_ALTERNATE = ('bch0.kister.net', 51002)
# Entradas heredadas de CashMiner que conectaban a MAINNET por error.
TESTNET3_BAD_LEGACY = frozenset((host, 50002) for host in
    ('bch0.kister.net', 'tbch.loping.net', 'blackie.c3-soft.com'))


# Max outstanding JSON-RPC requests on one TLS socket. Edit this constant,
# not a user preference. Conservative versus ElectrumX's default concurrency.
ELECTRUM_MAX_CONCURRENT_REQUESTS = 8


class ElectrumError(RuntimeError):
    pass


class ElectrumRPCError(ElectrumError):
    """An explicit JSON-RPC error sent by an Electrum server, not a transport fault."""
    def __init__(self, method: str, response):
        self.method = method
        self.code = response.get('code') if isinstance(response, dict) else None
        detail = response.get('message', 'Error remoto') if isinstance(response, dict) else response
        if not isinstance(detail, str):
            detail = str(detail)
        # A server is untrusted. Do not copy unbounded text to UI or logs.
        super().__init__(f'Electrum {method}: {detail[:180]}')


class ElectrumClient:
    def __init__(self, network: str, host: str, port: int, timeout: float = 9, *, cert_sha256: str | None = None):
        self.network, self.host, self.port = network, host, port
        self.timeout = timeout
        if cert_sha256 is not None:
            cert_sha256 = cert_sha256.lower().replace(':', '').strip()
            if not re.fullmatch(r'[0-9a-f]{64}', cert_sha256):
                raise ElectrumError('Huella SHA-256 del certificado inválida')
        self.cert_sha256 = cert_sha256
        self.sock = None
        self._recvbuf = b""
        self.sequence = 0
        self.notifications = []
        self.tip = None
        self.protocol_version = None

    def __enter__(self):
        if self.network not in NETWORK_GENESIS:
            raise ElectrumError('No hay una cadena de referencia compatible para esta red')
        # Conexiones comunes: CA y nombre de servidor verificados por el sistema.
        # Sólo servidores que el usuario agregó explícitamente con una huella
        # exacta pueden usar TLS con certificado autofirmado. La pinning SHA-256
        # sustituye la validación por CA y es obligatoria antes de mandar RPC.
        if self.cert_sha256 is None:
            ctx = ssl.create_default_context()
        else:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        sock = socket.create_connection((self.host,self.port),timeout=self.timeout)
        try:
            self.sock = ctx.wrap_socket(sock,server_hostname=self.host)
            if self.cert_sha256 is not None:
                actual = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
                if not hmac.compare_digest(actual, self.cert_sha256):
                    raise ElectrumError('Certificado TLS distinto de la huella aprobada')
            self.sock.settimeout(self.timeout)
            self._recvbuf = b""
            version_reply = self.rpc('server.version', ['CashMinerWallet/2.9', ['1.4', '1.5']])
            if (not isinstance(version_reply,list) or len(version_reply)<2 or
                not isinstance(version_reply[1],str)):
                raise ElectrumError('Negociación de protocolo Electrum inválida')
            self.protocol_version=version_reply[1]
            # With protocol 1.4, listunspent silently excludes CashTokens UTXOs.
            # An incomplete UTXO set must not be advertised as a complete balance.
            try:
                parts=tuple(int(x) for x in self.protocol_version.split('.')[:2])
            except ValueError as exc:
                raise ElectrumError('Versión de protocolo Electrum inválida') from exc
            if parts < (1,5):
                raise ElectrumError('Servidor Electrum anterior a 1.5: no garantiza incluir CashTokens')
            features = self.rpc('server.features', [])
            if not isinstance(features,dict) or features.get('genesis_hash','').lower() != NETWORK_GENESIS[self.network]:
                raise ElectrumError('Servidor de cadena incorrecta: hash génesis no coincide')
            # Bitcoin BTC and BCH share mainnet genesis. Pin the BCH fork block.
            if self.network == BCH_FORK_CHECKPOINT[0]:
                raw = self.rpc('blockchain.block.header', [BCH_FORK_CHECKPOINT[1]])
                if (not isinstance(raw,str) or len(raw)!=160 or
                    sha256d(bytes.fromhex(raw))[::-1].hex() != BCH_FORK_CHECKPOINT[2]):
                    raise ElectrumError('El proveedor no sigue BCH Mainnet (checkpoint UAHF)')
            if self.network in NETWORK_POSTFORK_CHECKPOINTS:
                height, expected = NETWORK_POSTFORK_CHECKPOINTS[self.network]
                raw = self.rpc('blockchain.block.header', [height])
                if (not isinstance(raw,str) or len(raw)!=160 or
                    sha256d(bytes.fromhex(raw))[::-1].hex() != expected):
                    raise ElectrumError(
                        f'Servidor no pertenece a {self.network}: checkpoint {height} incorrecto')
            self.tip = self.rpc('blockchain.headers.subscribe', [])
            if not isinstance(self.tip,dict) or 'height' not in self.tip or 'hex' not in self.tip:
                raise ElectrumError('El proveedor no respondió con la punta de cadena')
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self,*args):
        self.close()

    def close(self):
        if self.sock:
            try: self.sock.close()
            except Exception: pass
        self.sock = None
        self._recvbuf = b""

    def _read(self):
        # Do NOT use socket.makefile() here: Python's buffered reader can become
        # permanently unusable after a socket timeout, breaking subscriptions.
        while b"\n" not in self._recvbuf:
            if len(self._recvbuf)>2_000_000:
                raise ElectrumError('Respuesta Electrum demasiado grande')
            data=self.sock.recv(65536)
            if not data:
                raise ElectrumError('Servidor Electrum desconectado')
            self._recvbuf+=data
        line,self._recvbuf=self._recvbuf.split(b"\n",1)
        if len(line)>2_000_000:
            raise ElectrumError('Respuesta Electrum demasiado grande')
        try: value = json.loads(line)
        except (UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise ElectrumError('Respuesta JSON inválida') from exc
        if not isinstance(value,dict): raise ElectrumError('Respuesta Electrum inválida')
        return value

    def _notification(self,obj):
        method = obj.get('method')
        params = obj.get('params')
        if method == 'blockchain.headers.subscribe' and isinstance(params,list) and params:
            self.tip = params[0]
        elif method == 'blockchain.scripthash.subscribe' and isinstance(params,list) and len(params)>=2:
            self.notifications.append((params[0],params[1]))

    def rpc(self,method: str, params: list):
        if not self.sock: raise ElectrumError('Electrum desconectado')
        self.sequence+=1
        key=self.sequence
        request=json.dumps({'jsonrpc':'2.0','id':key,'method':method,'params':params},separators=(',',':'))
        if len(request)>100000: raise ElectrumError('Consulta demasiado grande')
        self.sock.sendall((request+'\n').encode('utf-8'))
        for _ in range(500):
            obj=self._read()
            if obj.get('id')==key:
                if obj.get('error') is not None:
                    raise ElectrumRPCError(method, obj['error'])
                return obj.get('result')
            if obj.get('method'):
                self._notification(obj)
        raise ElectrumError('Demasiadas notificaciones durante una consulta')

    def rpc_many(self, calls: list[tuple[str, list]], *, limit: int | None = None) -> list:
        """Pipeline independent Electrum JSON-RPC calls on the live TLS connection.

        One writer and one reader, both in the wallet worker thread. Replies are
        matched by id (never arrival order), and notifications still update the
        same subscription queue. Drain all requested replies before returning an
        RPC error so later calls don't encounter orphan replies.
        """
        if not self.sock: raise ElectrumError('Electrum desconectado')
        if limit is None: limit = ELECTRUM_MAX_CONCURRENT_REQUESTS
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError('Límite de consultas Electrum inválido')
        if not calls: return []
        if len(calls)>10000: raise ElectrumError('Demasiadas consultas Electrum')
        requests = deque(enumerate(calls))
        pending = {}
        result = [None] * len(calls)
        failure = None
        while requests or pending:
            while requests and len(pending)<limit:
                idx,(method,params) = requests.popleft()
                self.sequence += 1
                key = self.sequence
                request=json.dumps({'jsonrpc':'2.0','id':key,'method':method,'params':params},separators=(',',':'))
                if len(request)>100000: raise ElectrumError('Consulta demasiado grande')
                self.sock.sendall((request+'\n').encode('utf-8'))
                pending[key]=(idx,method)
            # Ignore unsolicited notifications, but enforce a finite ceiling.
            for _ in range(500):
                obj=self._read()
                if obj.get('method'):
                    self._notification(obj)
                    continue
                key=obj.get('id')
                if type(key) is not int or key not in pending:
                    raise ElectrumError('Respuesta Electrum inesperada o duplicada')
                idx,method=pending.pop(key)
                if obj.get('error') is not None:
                    if failure is None:
                        failure=ElectrumRPCError(method,obj['error'])
                else:
                    result[idx]=obj.get('result')
                break
            else:
                raise ElectrumError('Demasiadas notificaciones durante consultas')
        if failure is not None: raise failure
        return result

    def check_notifications(self, timeout: float = 1.0):
        self.sock.settimeout(timeout)
        try:
            obj=self._read()
            if obj.get('method'): self._notification(obj)
        except socket.timeout:
            return
        finally:
            self.sock.settimeout(self.timeout)

    def tip_height_hash(self):
        tip = self.tip
        if not isinstance(tip,dict) or not isinstance(tip.get('hex'),str) or len(tip['hex'])!=160:
            raise ElectrumError('Punta de cadena inválida')
        height=tip.get('height')
        if not isinstance(height,int) or height<0:
            raise ElectrumError('Altura de cadena inválida')
        blockhash=sha256d(bytes.fromhex(tip['hex']))[::-1].hex()
        return height,blockhash


def available_servers(network, stored):
    # Prefer explicitly configured endpoints, then published BCH-only endpoints.
    pairs = [(s['host'],s['port']) for s in stored]
    if network == 'testnet3':
        # No intentar Mainnet aunque un perfil anterior guarde puertos erróneos.
        pairs = [item for item in pairs if item not in TESTNET3_BAD_LEGACY]
    for item in DEFAULT_SERVERS.get(network,[]):
        if item not in pairs: pairs.append(item)
    return pairs
