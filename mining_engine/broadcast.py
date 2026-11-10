#!/usr/bin/env python3
"""
Broadcaster P2P mínimo para bloques BCH.

Objetivo:
- conectarse a peers BCH por TCP
- hacer handshake version/verack
- anunciar un bloque con inv
- responder a getdata con el bloque completo

Pensado primero para REGTEST, pero parametrizable para otras redes.
No implementa nodo completo, mempool ni validación de chainstate.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import os
import random
import select
import socket
import struct

PEER_EVENT_SINK = None  # Optional process-local observer, never a protocol decision.
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

PROTOCOL_VERSION = 70016
NODE_NETWORK = 1
NODE_BLOOM = 1 << 2
NODE_BITCOIN_CASH = 1 << 5

SERVICE_FLAGS = NODE_NETWORK | NODE_BLOOM | NODE_BITCOIN_CASH

USER_AGENT = b"/AlanBlockBroadcaster:0.1.0/"
DEFAULT_HANDSHAKE_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 3.0
DEFAULT_ANNOUNCE_TIMEOUT = 3.0

BROADCAST_MAX_CONCURRENT_PEERS = 50

BLOCK_INV_TYPE = 2
CMPCT_BLOCK_INV_TYPE = 4  # MSG_CMPCT_BLOCK: peers con sendcmpct piden el bloque así.
PING_NONCE_SIZE = 8
DEBUG_ENABLED = False

# Tope de tamaño para el payload de un mensaje P2P. El mensaje legítimo más grande
# es un 'block' (~32MB en testnet4); nada supera eso. Si el stream se desincroniza
# (header desalineado o peer mandando basura), payload_len puede leerse como un
# valor enorme (hasta ~4GB) que dejaría a recv_exact colgado esperando bytes que
# nunca llegan hasta el hard_timeout. Cortamos rápido con P2PError apenas el
# payload_len declarado supera este cap. 64MiB da margen a bloques grandes y sigue
# muy por debajo del rango de corrupción típico.
MAX_P2P_MESSAGE_SIZE = 64 * 1024 * 1024  # 64 MiB

# Nota: mainnet usa el "cash message start"; regtest/testnet pueden variar entre implementaciones.
# Estos valores están puestos para regtest local con BCHN/derivados en escenarios comunes.
# Si tu peer usa otros magic bytes, cambialos acá o pasalos por parámetro.
NETWORKS = {
    "mainnet": {"magic": bytes.fromhex("e3e1f3e8"), "port": 8333},
    "testnet": {"magic": bytes.fromhex("f4e5f3f4"), "port": 18333},
    "testnet4": {"magic": bytes.fromhex("e2b7daaf"), "port": 28333},
    "chipnet": {"magic": bytes.fromhex("e2b7daaf"), "port": 48333},
    "tempnet": {"magic": bytes.fromhex("e2b7daaf"), "port": 48333},
    "regtest": {"magic": bytes.fromhex("dab5bffa"), "port": 18444},
}


@dataclass(frozen=True)
class PeerTarget:
    host: str
    port: int


@dataclass(frozen=True)
class NetworkParams:
    name: str
    magic: bytes
    port: int


class P2PError(RuntimeError):
    pass


class HandshakeError(P2PError):
    pass


class BroadcastResult:
    def __init__(self, peer: PeerTarget, ok: bool, detail: str):
        self.peer = peer
        self.ok = ok
        self.detail = detail
        self.block_sent = False

    def __repr__(self) -> str:
        state = "OK" if self.ok else "FAIL"
        return f"[{state}] {self.peer.host}:{self.peer.port} - {self.detail}"



def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()



def pack_compact_size(n: int) -> bytes:
    if n < 0:
        raise ValueError("compact size negativo")
    if n < 253:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)



def unpack_compact_size(buf: io.BytesIO) -> int:
    first = buf.read(1)
    if len(first) != 1:
        raise EOFError("compact size incompleto")
    fb = first[0]
    if fb < 253:
        return fb
    if fb == 253:
        raw = buf.read(2)
        if len(raw) != 2:
            raise EOFError("compact size uint16 incompleto")
        return struct.unpack("<H", raw)[0]
    if fb == 254:
        raw = buf.read(4)
        if len(raw) != 4:
            raise EOFError("compact size uint32 incompleto")
        return struct.unpack("<I", raw)[0]
    raw = buf.read(8)
    if len(raw) != 8:
        raise EOFError("compact size uint64 incompleto")
    return struct.unpack("<Q", raw)[0]



def ip_to_netaddr(ip: str) -> bytes:
    """Soporta IPv4; IPv6 literal podría agregarse más adelante."""
    packed = socket.inet_aton(ip)
    return b"\x00" * 10 + b"\xff\xff" + packed



def build_message(magic: bytes, command: str, payload: bytes) -> bytes:
    if len(magic) != 4:
        raise ValueError("magic debe tener 4 bytes")
    cmd = command.encode("ascii")
    if len(cmd) > 12:
        raise ValueError("command demasiado largo")
    header = magic
    header += cmd.ljust(12, b"\x00")
    header += struct.pack("<I", len(payload))
    header += sha256d(payload)[:4]
    return header + payload



def recv_exact(sock: socket.socket, n: int, deadline: float = None) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise P2PError(f"recv_exact: deadline expirado con {remaining}/{n} bytes pendientes")
            sock.settimeout(left)
        data = sock.recv(remaining)
        if not data:
            raise ConnectionError("socket cerrado")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)



def read_message(sock: socket.socket, expected_magic: bytes,
                  msg_timeout: float = None) -> Tuple[str, bytes]:
    deadline = (time.monotonic() + msg_timeout) if msg_timeout else None
    old_timeout = sock.gettimeout()
    try:
        header = recv_exact(sock, 24, deadline)
        magic = header[:4]
        if magic != expected_magic:
            raise P2PError(f"magic inesperado: {magic.hex()} != {expected_magic.hex()}")
        command = header[4:16].rstrip(b"\x00").decode("ascii", errors="replace")
        payload_len = struct.unpack("<I", header[16:20])[0]
        checksum = header[20:24]
        if payload_len > MAX_P2P_MESSAGE_SIZE:
            raise P2PError(
                f"payload_len={payload_len} excede el máximo {MAX_P2P_MESSAGE_SIZE} "
                f"(command={command!r}); stream probablemente desincronizado"
            )
        payload = recv_exact(sock, payload_len, deadline)
        if sha256d(payload)[:4] != checksum:
            raise P2PError(f"checksum inválido para command={command}")
        return command, payload
    finally:
        if msg_timeout is not None:
            sock.settimeout(old_timeout)



def build_version_payload(local_ip: str, local_port: int, remote_ip: str, remote_port: int,
                          relay: bool = False) -> bytes:
    now = int(time.time())
    nonce = random.getrandbits(64)
    payload = struct.pack("<iQQ", PROTOCOL_VERSION, SERVICE_FLAGS, now)
    payload += struct.pack("<Q", SERVICE_FLAGS)
    payload += ip_to_netaddr(remote_ip)
    payload += struct.pack(">H", remote_port)
    payload += struct.pack("<Q", 0)
    payload += ip_to_netaddr(local_ip)
    payload += struct.pack(">H", local_port)
    payload += struct.pack("<Q", nonce)
    payload += pack_compact_size(len(USER_AGENT)) + USER_AGENT
    payload += struct.pack("<i", 0)  # start_height
    payload += (b"\x01" if relay else b"\x00")
    return payload



def parse_inv_payload(payload: bytes) -> List[Tuple[int, bytes]]:
    buf = io.BytesIO(payload)
    count = unpack_compact_size(buf)
    items: List[Tuple[int, bytes]] = []
    for _ in range(count):
        raw = buf.read(36)
        if len(raw) != 36:
            raise P2PError("inv/getdata truncado")
        inv_type = struct.unpack("<I", raw[:4])[0]
        inv_hash = raw[4:36]
        items.append((inv_type, inv_hash))
    return items



def build_inv_payload(inv_type: int, object_hash_le: bytes) -> bytes:
    if len(object_hash_le) != 32:
        raise ValueError("hash debe tener 32 bytes")
    return pack_compact_size(1) + struct.pack("<I", inv_type) + object_hash_le



def build_multi_inv_payload(inv_type: int, hashes_le: Sequence[bytes]) -> bytes:
    """
    Empaqueta múltiples entradas (type, hash) en un mensaje inv/getdata.
    hashes_le: lista de hashes en little-endian (32 bytes cada uno).
    """
    if not hashes_le:
        raise ValueError("hashes_le no puede estar vacío")
    if len(hashes_le) > 50000:
        raise ValueError("un inv/getdata acepta como máximo 50000 entradas")
    buf = pack_compact_size(len(hashes_le))
    packed_type = struct.pack("<I", inv_type)
    for h in hashes_le:
        if len(h) != 32:
            raise ValueError("hash debe tener 32 bytes")
        buf += packed_type + h
    return buf



def parse_block_hashes_from_getdata(payload: bytes) -> List[bytes]:
    found: List[bytes] = []
    for inv_type, inv_hash in parse_inv_payload(payload):
        # Los nodos que negociaron sendcmpct piden el bloque como
        # MSG_CMPCT_BLOCK (type 4). El protocolo permite responder con un
        # mensaje 'block' completo, así que tratamos type 2 y type 4 igual.
        if inv_type == BLOCK_INV_TYPE or inv_type == CMPCT_BLOCK_INV_TYPE:
            found.append(inv_hash)
    return found



def block_hash_le_from_block(block_bytes: bytes) -> bytes:
    if len(block_bytes) < 80:
        raise ValueError("bloque incompleto: menos de 80 bytes")
    return sha256d(block_bytes[:80])
    
    
    
def build_headers_payload(block_bytes: bytes) -> bytes:
    if len(block_bytes) < 80:
        raise ValueError("bloque incompleto: menos de 80 bytes")
    header = block_bytes[:80]
    # mensaje headers = count + (80-byte header + txcount=0)
    return pack_compact_size(1) + header + b"\x00"
    
    
    
def parse_getheaders_payload(payload: bytes) -> tuple[int, list[bytes], bytes]:
    buf = io.BytesIO(payload)
    version_raw = buf.read(4)
    if len(version_raw) != 4:
        raise P2PError("getheaders truncado en version")
    version = struct.unpack("<I", version_raw)[0]
    count = unpack_compact_size(buf)
    locators = []
    for _ in range(count):
        h = buf.read(32)
        if len(h) != 32:
            raise P2PError("getheaders truncado en locator")
        locators.append(h)
    stop_hash = buf.read(32)
    if len(stop_hash) != 32:
        raise P2PError("getheaders truncado en stop hash")
    return version, locators, stop_hash
    
    
    
def read_compact_size_from_bytesio(buf: io.BytesIO) -> int:
    first = buf.read(1)
    if len(first) != 1:
        raise P2PError("compact size incompleto")
    fb = first[0]
    if fb < 253:
        return fb
    if fb == 253:
        raw = buf.read(2)
        if len(raw) != 2:
            raise P2PError("compact size uint16 incompleto")
        return struct.unpack("<H", raw)[0]
    if fb == 254:
        raw = buf.read(4)
        if len(raw) != 4:
            raise P2PError("compact size uint32 incompleto")
        return struct.unpack("<I", raw)[0]
    raw = buf.read(8)
    if len(raw) != 8:
        raise P2PError("compact size uint64 incompleto")
    return struct.unpack("<Q", raw)[0]


def read_varstr(buf: io.BytesIO) -> bytes:
    ln = read_compact_size_from_bytesio(buf)
    data = buf.read(ln)
    if len(data) != ln:
        raise P2PError("varstr truncado")
    return data


def parse_reject_payload(payload: bytes) -> dict:
    """
    reject payload:
    - message: varstr
    - ccode: uint8
    - reason: varstr
    - data: bytes restantes (opcional; en blocks suele ser hash LE)
    """
    buf = io.BytesIO(payload)

    message = read_varstr(buf).decode("ascii", errors="replace")

    code_raw = buf.read(1)
    if len(code_raw) != 1:
        raise P2PError("reject truncado en code")
    code = code_raw[0]

    reason = read_varstr(buf).decode("ascii", errors="replace")

    extra = buf.read()
    extra_hex = extra.hex()

    extra_hash_be = None
    if len(extra) == 32:
        extra_hash_be = extra[::-1].hex()

    return {
        "message": message,
        "code": code,
        "reason": reason,
        "extra_hex": extra_hex,
        "extra_hash_be": extra_hash_be,
    }
    
    
    
def build_empty_headers_payload() -> bytes:
    return b"\x00"



class BlockBroadcaster:
    def __init__(
        self,
        network: str = "regtest",
        timeout: float = DEFAULT_READ_TIMEOUT,
        handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
        announce_timeout: float = DEFAULT_ANNOUNCE_TIMEOUT,
        magic_override_hex: Optional[str] = None,
    ):
        if network not in NETWORKS:
            raise ValueError(f"red no soportada: {network}")
        cfg = NETWORKS[network]
        magic = bytes.fromhex(magic_override_hex) if magic_override_hex else cfg["magic"]
        self.params = NetworkParams(name=network, magic=magic, port=cfg["port"])
        self.timeout = timeout
        self.handshake_timeout = handshake_timeout
        self.announce_timeout = announce_timeout

    def connect(self, peer: PeerTarget) -> socket.socket:
        self._observe(peer,'connect_attempt')
        try:
            sock = socket.create_connection((peer.host, peer.port), timeout=self.handshake_timeout)
            sock.settimeout(self.timeout)
        except Exception as exc:
            self._observe(peer,'tcp_fail',status=str(exc)[:250]);raise
        self._observe(peer,'tcp_ok')
        return sock

    def _observe(self, peer, kind, **fields):
        if PEER_EVENT_SINK is not None:
            try:
                PEER_EVENT_SINK(dict(network=self.params.name,ip=peer.host.strip('[]'),port=peer.port,
                    ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),kind=kind,**fields))
            except Exception:pass  # Observations cannot interrupt mining.

    def _send(self, sock: socket.socket, command: str, payload: bytes = b"") -> None:
        sock.sendall(build_message(self.params.magic, command, payload))

    def _handshake(self, sock: socket.socket, peer: PeerTarget) -> dict:
        try:metadata=self._handshake_impl(sock,peer)
        except Exception as exc:
            self._observe(peer,'handshake_fail',status=str(exc)[:250]);raise
        self._observe(peer,'handshake_ok',**metadata)
        return metadata

    def _handshake_impl(self, sock: socket.socket, peer: PeerTarget):
        local_ip = "127.0.0.1"
        local_port = random.randint(10000, 60000)
        version_payload = build_version_payload(local_ip=local_ip, local_port=local_port,
                                               remote_ip="127.0.0.1",
                                               remote_port=peer.port)
        self._send(sock, "version", version_payload)
        got_version = False
        got_verack = False
        metadata={}
        deadline = time.time() + self.handshake_timeout

        while time.time() < deadline and not (got_version and got_verack):
            command, payload = read_message(sock, self.params.magic, msg_timeout=10.0)
            if command == "version":
                got_version = True
                try:
                    if len(payload)>=81:
                        metadata={'protocol_version':struct.unpack('<i',payload[:4])[0],
                                  'services':struct.unpack('<Q',payload[4:12])[0],
                                  'user_agent':read_varstr(io.BytesIO(payload[80:])).decode('utf8',errors='replace')[:160]}
                except Exception:metadata={}
                self._send(sock, "verack")
            elif command == "verack":
                got_verack = True
            elif command == "ping":
                self._send(sock, "pong", payload)
            elif command in {"sendheaders", "sendcmpct", "feefilter", "wtxidrelay", "protoconf", "extversion"}:
                continue
            else:
                continue

        if not (got_version and got_verack):
            raise HandshakeError(f"handshake incompleto con {peer.host}:{peer.port}")
        return metadata

    @staticmethod
    def _is_ipv4(host: str) -> bool:
        try:
            socket.inet_aton(host)
            return True
        except OSError:
            return False

    def handshake_only(self, peer: PeerTarget) -> None:
        sock = self.connect(peer)
        try:
            self._handshake(sock, peer)
        finally:
            sock.close()

    def announce_block(self, peer: PeerTarget, block_bytes: bytes, wait_for_getdata: bool = True) -> BroadcastResult:
        
        headers_sent = False
        peer_requested_block = False
        
        reject_info = None
        block_sent = False

        def outcome(ok, detail):
            result=BroadcastResult(peer,ok,detail)
            result.block_sent=block_sent
            return result
        
        block_hash_le = block_hash_le_from_block(block_bytes)
        sock = self.connect(peer)
        try:
            self._handshake(sock, peer)
            self._send(sock, "inv", build_inv_payload(BLOCK_INV_TYPE, block_hash_le))

            if not wait_for_getdata:
                return outcome(True, f"inv enviado para {block_hash_le[::-1].hex()}")

            deadline = time.time() + self.announce_timeout
            while time.time() < deadline:
                try:
                    command, payload = read_message(sock, self.params.magic, msg_timeout=10.0)
                except socket.timeout:
                    break

                if DEBUG_ENABLED:
                    print(f"[DEBUG] recibido command={command} len={len(payload)}")
                if command == "getdata":
                    requested_hashes = parse_block_hashes_from_getdata(payload)
                    if block_hash_le in requested_hashes:
                        peer_requested_block = True
                        self._send(sock, "block", block_bytes)
                        block_sent = True
                        if DEBUG_ENABLED:
                            print(f"[DEBUG] bloque enviado a {peer.host}:{peer.port} hash={block_hash_le[::-1].hex()}")
                        continue

                elif command == "getheaders":
                    version, locators, stop_hash = parse_getheaders_payload(payload)

                    my_header = block_bytes[:80]
                    my_block_hash_le = sha256d(my_header)
                    my_prev_hash_le = my_header[4:36]
                    
                    if DEBUG_ENABLED:
                        print(f"[DEBUG] prev={my_prev_hash_le[::-1].hex()} block={my_block_hash_le[::-1].hex()} stop={stop_hash[::-1].hex()} locators={[h[::-1].hex() for h in locators]}")

                    should_send = False

                    if my_prev_hash_le in locators:
                        should_send = True
                    elif stop_hash == my_block_hash_le:
                        should_send = True

                    if should_send:
                        if DEBUG_ENABLED:
                            print("[DEBUG] respondiendo con headers del bloque")
                        self._send(sock, "headers", build_headers_payload(block_bytes))
                        headers_sent = True
                    else:
                        if DEBUG_ENABLED:
                            print("[DEBUG] respondiendo con headers vacio")
                        self._send(sock, "headers", build_empty_headers_payload())

                elif command == "ping":
                    self._send(sock, "pong", payload)
                    
                elif command == "reject":
                    try:
                        info = parse_reject_payload(payload)
                        reject_info = info

                        if DEBUG_ENABLED:
                            print(
                                "[DEBUG] reject recibido "
                                f"peer={peer.host}:{peer.port} "
                                f"message={info['message']} "
                                f"code=0x{info['code']:02x} "
                                f"reason={info['reason']} "
                                f"extra_hash={info['extra_hash_be']} "
                                f"extra_hex={info['extra_hex']}"
                            )

                    except Exception as e:
                        if DEBUG_ENABLED:
                            print(f"[DEBUG] error parseando reject: {e}")

                elif command in {"inv", "headers", "addr", "sendheaders", "sendcmpct", "feefilter", "protoconf", "extversion"}:
                    continue

            if reject_info is not None:
                return outcome(
                    False,
                    "peer rechazo block "
                    f"message={reject_info['message']} "
                    f"code=0x{reject_info['code']:02x} "
                    f"reason={reject_info['reason']} "
                    f"extra_hash={reject_info['extra_hash_be']}"
                )

            if block_sent:
                return outcome(
                    True,
                    f"peer pidió el bloque y fue enviado: {block_hash_le[::-1].hex()}"
                )

            if headers_sent and not peer_requested_block:
                return outcome(
                    True,
                    f"peer aceptó/anunció headers pero no pidió block: {block_hash_le[::-1].hex()}"
                )

            return outcome(False, "timeout esperando getdata/reject o reaccion del peer")
            
        except Exception as e:
            return outcome(False, str(e))
            
        finally:
            sock.close()

    def broadcast_block(
        self,
        peers: Sequence[PeerTarget],
        block_hex: str,
        wait_for_getdata: bool = True,
        max_concurrent_peers: int = BROADCAST_MAX_CONCURRENT_PEERS,
    ) -> List[BroadcastResult]:
        block_bytes = bytes.fromhex(block_hex)

        if not peers:
            return []

        max_workers = max(1, min(int(max_concurrent_peers), len(peers)))
        results: List[BroadcastResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_peer = {
                executor.submit(
                    self.announce_block,
                    peer,
                    block_bytes,
                    wait_for_getdata,
                ): peer
                for peer in peers
            }

            for future in as_completed(future_to_peer):
                peer = future_to_peer[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = BroadcastResult(peer, False, f"error interno worker: {e}")
                results.append(result)

        return results

    def announce_fake_block_hash(self, peer: PeerTarget, block_hash_be_hex: str) -> BroadcastResult:
        if len(block_hash_be_hex) != 64:
            raise ValueError("hash BE hex debe tener 64 caracteres hex")
        block_hash_le = bytes.fromhex(block_hash_be_hex)[::-1]
        sock = self.connect(peer)
        try:
            self._handshake(sock, peer)
            self._send(sock, "inv", build_inv_payload(BLOCK_INV_TYPE, block_hash_le))
            deadline = time.time() + self.announce_timeout
            while time.time() < deadline:
                command, payload = read_message(sock, self.params.magic, msg_timeout=10.0)
                if command == "getdata":
                    requested_hashes = parse_block_hashes_from_getdata(payload)
                    if block_hash_le in requested_hashes:
                        return BroadcastResult(peer, True, f"peer pidió el hash inventado {block_hash_be_hex}")
                elif command == "ping":
                    self._send(sock, "pong", payload)
                else:
                    continue
            return BroadcastResult(peer, False, "timeout esperando getdata")
        except Exception as e:
            return BroadcastResult(peer, False, str(e))
        finally:
            sock.close()



class MempoolFetcher(BlockBroadcaster):
    """
    Fetcher de mempool vía P2P.

    Flujo:
      handshake → 'mempool' → recibir inv(MSG_TX) → 'getdata' → recibir 'tx'... → done

    Reutiliza connect/_handshake/_send/read_message de BlockBroadcaster.
    NO valida las txs — confía en el peer. Devuelve las txs crudas indexadas por txid BE hex.
    """

    MSG_TX = 1
    _GETDATA_BATCH = 500
    _POLL_INTERVAL = 1.0   # s: poll de lectura para re-evaluar idle/hard timeout

    def fetch_mempool(
        self,
        peer: PeerTarget,
        idle_timeout: float = 6.0,
        hard_timeout: float = 30.0,
        max_txs: Optional[int] = None,
    ) -> dict:
        """
        Devuelve dict[txid_be_hex] -> raw_tx_bytes.
        - idle_timeout: si no llegan mensajes nuevos por N segundos, cortamos.
        - hard_timeout: cota superior absoluta desde el inicio.
        - max_txs: si está seteado, limita cuántas txs pedimos (útil para tests).
        """
        sock = self.connect(peer)
        try:
            self._handshake(sock, peer)
            self._send(sock, "mempool", b"")
            sock.settimeout(idle_timeout)   # cota para sendall (getdata/pong)

            wanted: set = set()      # txids_le que ya pedimos o recibimos
            in_flight: set = set()   # txids_le que pedimos pero todavía no llegaron
            received: dict = {}      # txid_be_hex -> raw payload
            start = time.time()
            last_activity = time.time()
            mempool_inv_seen = False

            while True:
                now = time.time()
                if now - start > hard_timeout:
                    break
                if now - last_activity > idle_timeout:
                    break
                # Si ya arrancó a llegar inv y ya no quedan en vuelo, terminamos.
                if mempool_inv_seen and not in_flight:
                    break

                # Poll corto de lectura antes de leer, para re-evaluar idle/hard
                # timeout de forma responsiva. Sin esto, read_message (vía
                # recv_exact) fija el timeout del socket al deadline completo y
                # bloquea hasta hard_timeout esperando un header que no llega: el
                # idle_timeout nunca se evaluaba y un mempool vacío tardaba los
                # 30s enteros en cortar.
                ready, _, _ = select.select([sock], [], [], self._POLL_INTERVAL)
                if not ready:
                    continue

                try:
                    cmd, payload = read_message(sock, self.params.magic, msg_timeout=idle_timeout)
                except socket.timeout:
                    continue
                except (ConnectionError, P2PError):
                    break

                if cmd == "inv":
                    try:
                        items = parse_inv_payload(payload)
                    except Exception:
                        continue
                    tx_hashes = [h for (t, h) in items if t == self.MSG_TX]
                    new_hashes = [h for h in tx_hashes if h not in wanted]
                    if max_txs is not None:
                        room = max(0, max_txs - len(wanted))
                        new_hashes = new_hashes[:room]
                    if new_hashes:
                        # Solo un inv con txids NUEVOS de mempool cuenta como
                        # actividad. Un inv de anuncio de bloque u otro gossip no
                        # debe resetear el idle_timeout: si no, en una red con
                        # tráfico un mempool vacío nunca cortaría por idle.
                        last_activity = time.time()
                        mempool_inv_seen = True
                        wanted.update(new_hashes)
                        in_flight.update(new_hashes)
                        try:
                            for i in range(0, len(new_hashes), self._GETDATA_BATCH):
                                batch = new_hashes[i:i + self._GETDATA_BATCH]
                                self._send(sock, "getdata", build_multi_inv_payload(self.MSG_TX, batch))
                        except (ConnectionError, OSError):
                            break

                elif cmd == "tx":
                    last_activity = time.time()
                    txid_le = sha256d(payload)
                    txid_be_hex = txid_le[::-1].hex()
                    received[txid_be_hex] = payload
                    in_flight.discard(txid_le)

                elif cmd == "notfound":
                    last_activity = time.time()
                    try:
                        items = parse_inv_payload(payload)
                    except Exception:
                        continue
                    for (t, h) in items:
                        if t == self.MSG_TX:
                            in_flight.discard(h)

                elif cmd == "ping":
                    try:
                        self._send(sock, "pong", payload)
                    except (ConnectionError, OSError):
                        break

            return received
        finally:
            try:
                sock.close()
            except Exception:
                pass



def parse_peers(peer_args: Sequence[str], default_port: int) -> List[PeerTarget]:
    peers: List[PeerTarget] = []
    for item in peer_args:
        host, port = parse_host_port(item, default_port)
        peers.append(PeerTarget(host=host, port=port))
    return peers



def parse_host_port(value: str, default_port: int) -> Tuple[str, int]:
    if value.startswith("["):
        # IPv6 tipo [::1]:18444
        right = value.find("]")
        if right == -1:
            raise ValueError(f"peer inválido: {value}")
        host = value[1:right]
        rest = value[right + 1:]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, default_port
    if value.count(":") == 1:
        host, port_s = value.rsplit(":", 1)
        return host, int(port_s)
    return value, default_port



def read_block_hex_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        data = f.read().strip()
    return "".join(data.split())



def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Broadcaster P2P mínimo para bloques BCH")
    p.add_argument("--network", choices=sorted(NETWORKS.keys()), default="regtest")
    p.add_argument("--peer", action="append", default=[], help="peer host[:port]. Repetible.")
    p.add_argument("--magic-override", help="magic bytes hex, por ejemplo fabfb5da")
    p.add_argument("--handshake-only", action="store_true", help="solo probar handshake")
    p.add_argument("--fake-inv-hash", help="anunciar un hash inventado (BE hex de 64 chars)")
    p.add_argument("--block-hex")
    p.add_argument("--block-file", help="archivo de texto con el bloque en hex")
    p.add_argument("--no-wait-getdata", action="store_true", help="no esperar getdata luego del inv")
    return p




def broadcast_block_hex(
    block_hex: str,
    peers: Sequence[str],
    network: str = "mainnet",
    magic_override_hex: Optional[str] = None,
    wait_for_getdata: bool = True,
    debug: bool = False,
    max_concurrent_peers: int = BROADCAST_MAX_CONCURRENT_PEERS,
) -> List[BroadcastResult]:
    global DEBUG_ENABLED
    DEBUG_ENABLED = bool(debug)
    cfg = NETWORKS[network]
    peer_objs = parse_peers(peers, cfg["port"])
    broadcaster = BlockBroadcaster(network=network, magic_override_hex=magic_override_hex)
    return broadcaster.broadcast_block(
        peer_objs,
        block_hex,
        wait_for_getdata=wait_for_getdata,
        max_concurrent_peers=max_concurrent_peers,
    )


def handshake_peers(peers: Sequence[str], network: str = "mainnet", magic_override_hex: Optional[str] = None) -> List[BroadcastResult]:
    cfg = NETWORKS[network]
    peer_objs = parse_peers(peers, cfg["port"])
    broadcaster = BlockBroadcaster(network=network, magic_override_hex=magic_override_hex)
    results = []
    for peer in peer_objs:
        try:
            broadcaster.handshake_only(peer)
            results.append(BroadcastResult(peer, True, "handshake ok"))
        except Exception as e:
            results.append(BroadcastResult(peer, False, str(e)))
    return results

def main() -> int:
    args = build_arg_parser().parse_args()
    cfg = NETWORKS[args.network]
    peers = parse_peers(args.peer or [f"127.0.0.1:{cfg['port']}"], cfg["port"])
    broadcaster = BlockBroadcaster(network=args.network, magic_override_hex=args.magic_override)

    if args.handshake_only:
        ok = True
        for peer in peers:
            try:
                broadcaster.handshake_only(peer)
                print(f"[OK] handshake con {peer.host}:{peer.port}")
            except Exception as e:
                ok = False
                print(f"[FAIL] handshake con {peer.host}:{peer.port}: {e}")
        return 0 if ok else 2

    if args.fake_inv_hash:
        ok = False
        for peer in peers:
            result = broadcaster.announce_fake_block_hash(peer, args.fake_inv_hash)
            print(result)
            ok = ok or result.ok
        return 0 if ok else 3

    block_hex = args.block_hex
    if not block_hex and args.block_file:
        block_hex = read_block_hex_from_file(args.block_file)

    if not block_hex:
        print("Falta --block-hex o --block-file, salvo que uses --handshake-only o --fake-inv-hash")
        return 1

    results = broadcaster.broadcast_block(peers, block_hex, wait_for_getdata=not args.no_wait_getdata)
    for result in results:
        print(result)
    return 0 if any(r.ok for r in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
