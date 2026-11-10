"""Explorador P2P saliente de bajo consumo, sin escuchar puertos.

El handshake no demuestra validez de consenso. getaddr solo aporta candidatos.
"""
from __future__ import annotations

import hashlib
import ipaddress
import random
import socket
import struct
import time
from dataclasses import dataclass

from cashminer.network.endpoints import eligible_public_ip, endpoint, normalize_ip, split_endpoint
from cashminer.network.networks import Network

PROTO_VERSION = 70016
SERVICES = 1 | (1 << 5)
AGENT = b'/CashMiner:2.9/'
MAX_MESSAGE = 2 * 1024 * 1024


def sha256d(blob: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(blob).digest()).digest()


def varint(n: int) -> bytes:
    if n < 253: return bytes((n,))
    if n <= 0xffff: return b'\xfd' + struct.pack('<H',n)
    if n <= 0xffffffff: return b'\xfe' + struct.pack('<I',n)
    return b'\xff' + struct.pack('<Q',n)


def read_varint(buf: memoryview, offset: int) -> tuple[int,int]:
    if offset >= len(buf): raise ValueError('varint truncado')
    n = buf[offset]; offset += 1
    if n < 253: return n,offset
    size = {253:2,254:4,255:8}[n]
    if offset+size > len(buf): raise ValueError('varint truncado')
    return int.from_bytes(buf[offset:offset+size],'little'),offset+size


def message(magic: bytes, command: str, payload: bytes = b'') -> bytes:
    raw = command.encode('ascii')
    if len(raw)>12: raise ValueError('comando demasiado largo')
    if len(payload)>MAX_MESSAGE: raise ValueError('mensaje demasiado grande')
    return magic + raw.ljust(12,b'\x00') + struct.pack('<I',len(payload)) + sha256d(payload)[:4] + payload


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('plazo absoluto de fase P2P agotado')
    return remaining


def _send_before(sock, packet, deadline):
    previous = sock.gettimeout()
    remaining = _remaining(deadline)
    sock.settimeout(min(previous, remaining) if isinstance(previous, (int, float)) else remaining)
    try:
        sock.sendall(packet)
    finally:
        sock.settimeout(previous)


def recv_exact(sock: socket.socket, count: int, *, deadline: float | None = None) -> bytes:
    chunks = []
    previous = sock.gettimeout() if deadline is not None else None
    try:
        while count:
            if deadline is not None:
                remaining = _remaining(deadline)
                sock.settimeout(min(previous, remaining) if previous is not None else remaining)
            b = sock.recv(min(count,65536))
            if not b: raise ConnectionError('peer cerró conexión')
            chunks.append(b); count -= len(b)
    finally:
        if deadline is not None:
            sock.settimeout(previous)
    return b''.join(chunks)


def recv_message(sock: socket.socket, magic: bytes, *, deadline: float | None = None) -> tuple[str,bytes]:
    header = recv_exact(sock,24,deadline=deadline)
    if header[:4] != magic:
        raise ValueError('magic P2P incompatible')
    command = header[4:16].rstrip(b'\x00').decode('ascii',errors='replace')
    n = struct.unpack('<I',header[16:20])[0]
    if n>MAX_MESSAGE: raise ValueError('payload supera límite explorador')
    payload = recv_exact(sock,n,deadline=deadline)
    if sha256d(payload)[:4] != header[20:24]: raise ValueError('checksum P2P inválido')
    return command,payload


def ip16(host: str) -> bytes:
    ip=ipaddress.ip_address(normalize_ip(host))
    return b'\x00'*10+b'\xff\xff'+ip.packed if ip.version==4 else ip.packed


def version_payload(host: str,port: int) -> bytes:
    now = int(time.time())
    out = struct.pack('<iQq',PROTO_VERSION,SERVICES,now)
    out += struct.pack('<Q',0)+ip16(host)+struct.pack('>H',port)
    out += struct.pack('<Q',0)+b'\x00'*16+struct.pack('>H',0)
    out += struct.pack('<Q',random.getrandbits(64))
    out += varint(len(AGENT))+AGENT+struct.pack('<i',0)+b'\x00'
    return out


def parse_version(payload: bytes) -> dict:
    if len(payload)<80: raise ValueError('version corta')
    version = int.from_bytes(payload[0:4],'little',signed=True)
    services = int.from_bytes(payload[4:12],'little')
    buf = memoryview(payload)
    ua_len,offset=read_varint(buf,80)
    if ua_len>256 or offset+ua_len>len(buf):raise ValueError('user agent inválido')
    agent=bytes(buf[offset:offset+ua_len]).decode('utf-8',errors='replace')
    return {'protocol_version':version,'services':services,'user_agent':agent}


def parse_addr(payload: bytes, limit: int = 1000) -> list[tuple[str,int]]:
    buf=memoryview(payload)
    count,offset=read_varint(buf,0)
    if count>1000: raise ValueError('demasiados peers anunciados')
    if len(buf)-offset!=count*30: raise ValueError('payload addr inválido')
    found=[]
    for _ in range(count):
        item=buf[offset:offset+30]; offset+=30
        ip=ipaddress.ip_address(bytes(item[12:28]))
        if ip.version==6 and ip.ipv4_mapped:ip=ip.ipv4_mapped
        port=struct.unpack('>H',item[28:30])[0]
        if port and ip.is_global:
            found.append((str(ip),port))
        if len(found)>=limit:break
    return list(dict.fromkeys(found))


@dataclass
class Probe:
    ip: str
    port: int
    connected: bool = False
    handshake: bool = False
    addr_received: bool = False
    latency_ms: float | None = None
    metadata: dict | None = None
    candidates: list[tuple[str,int]] | None = None
    error: str | None = None
    chain_status: str = 'unverified'  # handshake no equivale a identidad de cadena
    chain_note: str = ''


def _verify_checkpoint(sock: socket.socket, network: Network, timeout: float) -> tuple[str,str]:
    """Comprueba SOLO la cabecera que sigue al checkpoint conocido de FABLOUS.

    No es una validación de bloques completos, consenso, ni cadena acumulada.
    Una respuesta vacía o ambigua queda 'unverified', nunca se presupone válida.
    """
    if not network.identity_locator or not network.identity_first_hash:
        return 'unverified','La red no tiene un checkpoint configurado para esta sonda'
    request=(struct.pack('<I',PROTO_VERSION)+varint(1)+bytes.fromhex(network.identity_locator)[::-1]
             +bytes(32))
    deadline=time.monotonic()+timeout
    _send_before(sock,message(network.magic,'getheaders',request),deadline)
    while time.monotonic()<deadline:
        try:
            cmd,payload=recv_message(sock,network.magic,deadline=deadline)
        except (TimeoutError,OSError,ConnectionError) as exc:
            return 'unverified',f'Sin cabeceras de referencia: {str(exc)[:80]}'
        if cmd=='ping':
            _send_before(sock,message(network.magic,'pong',payload),deadline)
            continue
        if cmd!='headers':continue
        count,offset=read_varint(memoryview(payload),0)
        if not count:return 'unverified','Peer no devolvió cabeceras desde el checkpoint'
        if count>2000 or len(payload)<offset+81:
            return 'unverified','Respuesta de cabeceras incompleta'
        header=payload[offset:offset+80]
        if payload[offset+80]!=0:return 'unverified','Contador de transacciones del header inválido'
        previous=header[4:36][::-1].hex()
        digest=sha256d(header)[::-1].hex()
        if previous!=network.identity_locator:
            return 'unverified','Primera cabecera no enlaza al checkpoint solicitado'
        if digest==network.identity_first_hash:
            return 'compatible',f'Checkpoint coincidente: {digest[:16]}…'
        return 'incompatible',f'Cabecera de bifurcación incompatible: {digest[:16]}…'
    return 'unverified','Sin respuesta de cabeceras de referencia'


def _handshake(sock, network, host, port, timeout):
    """One absolute budget, shared by all header/payload reads and replies."""
    sock.settimeout(timeout)
    deadline=time.monotonic()+timeout*3
    _send_before(sock,message(network.magic,'version',version_payload(host,port)),deadline)
    metadata=None
    got_version=False;got_verack=False
    while not (got_version and got_verack):
        cmd,payload=recv_message(sock,network.magic,deadline=deadline)
        if cmd=='version':
            metadata=parse_version(payload)
            got_version=True
            _send_before(sock,message(network.magic,'verack'),deadline)
        elif cmd=='verack':got_verack=True
        elif cmd=='ping':_send_before(sock,message(network.magic,'pong',payload),deadline)
    return metadata


def probe_peer(network: Network, host: str, port: int, *, timeout: float=4.0,
               getaddr: bool=False, limit: int=100, verify_chain: bool=False) -> Probe:
    host = normalize_ip(host)
    result = Probe(host,port,candidates=[])
    start=time.monotonic()
    try:
        with socket.create_connection((host,port),timeout=timeout) as sock:
            result.connected=True
            result.metadata=_handshake(sock,network,host,port,timeout)
            result.handshake=True
            result.latency_ms=round((time.monotonic()-start)*1000,1)
            addr_failed=False
            if getaddr:
                try:
                    deadline=time.monotonic()+timeout
                    _send_before(sock,message(network.magic,'getaddr'),deadline)
                    while not result.addr_received:
                        cmd,payload=recv_message(sock,network.magic,deadline=deadline)
                        if cmd=='addr':
                            result.candidates=parse_addr(payload,limit=limit)
                            result.addr_received=True
                        elif cmd=='ping':_send_before(sock,message(network.magic,'pong',payload),deadline)
                except (OSError,ValueError,ConnectionError,TimeoutError) as exc:
                    addr_failed=True
                    result.error=f'getaddr: {str(exc)}'[:250]
                    # A timeout may have consumed a partial frame. Never reuse
                    # this byte stream for a different protocol phase.
                    sock.close()
            if verify_chain:
                try:
                    if addr_failed and network.identity_locator and network.identity_first_hash:
                        with socket.create_connection((host,port),timeout=timeout) as fresh:
                            _handshake(fresh,network,host,port,timeout)
                            result.chain_status,result.chain_note=_verify_checkpoint(fresh,network,timeout)
                    else:
                        result.chain_status,result.chain_note=_verify_checkpoint(sock,network,timeout)
                except (OSError,ValueError,ConnectionError,TimeoutError) as exc:
                    result.chain_status='unverified'
                    result.chain_note=f'No pudo comprobarse checkpoint: {str(exc)[:80]}'
    except (OSError,ValueError,ConnectionError,TimeoutError) as exc:
        result.error=str(exc)[:250]
    return result


def discover_dns(network: Network, *, limit: int = 40) -> list[tuple[str,int,str]]:
    found=[];seen=set()
    for seed in network.seeds:
        try:
            info=socket.getaddrinfo(seed,network.default_port,type=socket.SOCK_STREAM)
            for item in info:
                host=normalize_ip(item[4][0]);port=network.default_port
                if not eligible_public_ip(host) or (host,port) in seen:continue
                seen.add((host,port));found.append((host,port,seed))
                if len(found)>=limit:return found
        except OSError:
            continue
    return found
