"""Sincronización de headers de tempnet por P2P, sin Electrum ni RPC.

Se ancla al último bloque común de chipnet (327988), exige el primer
bloque específico de tempnet (327989), y verifica PoW y ASERT de los siguientes.
NO valida el UTXO set ni los scripts de las transacciones de la cadena.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Sequence
import io
import struct
import ipaddress
import socket

from broadcast import BlockBroadcaster, PeerTarget, read_message
from fablous.consensus import (
    ACTIVATION_HEIGHT, COMMON_HASH, FIRST_HASH, PEERS,
    block_work, parse_header, validate_header,
)


def _read_varint(f: io.BytesIO) -> int:
    marker = f.read(1)
    if not marker:
        raise ValueError("varint truncado")
    n = marker[0]
    if n < 253:
        return n
    lengths = {253: 2, 254: 4, 255: 8}
    data = f.read(lengths[n])
    if len(data) != lengths[n]:
        raise ValueError("varint truncado")
    return int.from_bytes(data, "little")


def _unpack_headers(payload: bytes) -> list[bytes]:
    f = io.BytesIO(payload)
    count = _read_varint(f)
    if count > 2000:
        raise ValueError("demasiados headers en un mensaje")
    result = []
    for _ in range(count):
        header = f.read(80)
        if len(header) != 80 or _read_varint(f) != 0:
            raise ValueError("payload headers inválido")
        result.append(header)
    if f.read(1):
        raise ValueError("bytes restantes en headers")
    return result


def _getheaders_payload(locator_hashes: list[str]) -> bytes:
    locator = b"".join(bytes.fromhex(h)[::-1] for h in locator_hashes)
    count = len(locator_hashes)
    if count >= 253:
        raise ValueError("demasiados hashes en locator")
    return struct.pack("<I", 70016) + bytes([count]) + locator + bytes(32)


def _unpack_addr(payload: bytes) -> list[str]:
    """Decodifica exclusivamente mensajes legacy addr (IPv4 mapeada).

    Son direcciones no autenticadas: cada candidato requiere comprobar
    el checkpoint, PoW y la dificultad antes de contarlo como peer tempnet.
    """
    f = io.BytesIO(payload)
    count = _read_varint(f)
    if count > 1000:
        raise ValueError("addr anuncia más de 1000 direcciones")
    result = []
    for _ in range(count):
        item = f.read(30)  # timestamp4, services8, IPv6-mapped16, port2
        if len(item) != 30:
            raise ValueError("addr truncado")
        raw_ip = item[12:28]
        port = struct.unpack(">H", item[28:30])[0]
        if raw_ip[:12] != b"\x00" * 10 + b"\xff\xff":
            continue  # IPv6 sin soporte en este cliente experimental
        ip = ipaddress.IPv4Address(raw_ip[12:])
        if port and ip.is_global:
            result.append(f"{ip}:{port}")
    if f.read(1):
        raise ValueError("bytes restantes en addr")
    return list(dict.fromkeys(result))


class TempnetHeaderClient:
    """Observador de cabeceras. Mantiene una cache SOLO en memoria."""

    def __init__(self, peers: Sequence[str] = PEERS, log: Optional[Callable[[str], None]] = None):
        self.peers = tuple(peers)
        self.allow_discovery = True
        self.log = log or (lambda _: None)
        self.chain: list[dict] = []  # headers 327989, 327990, ...
        self.work = 0
        self._wrong_chain_peers: set[str] = set()
        self.last_peers_ok: list[str] = []
        self._last_discovery_monotonic = -float("inf")

    @property
    def tip(self) -> dict:
        if not self.chain:
            raise RuntimeError("tempnet no sincronizado: no tengo cabeceras posteriores al fork")
        result = self.chain[-1].copy()
        result["tip_height"] = ACTIVATION_HEIGHT + len(self.chain)
        result["tip_hash_hex"] = result["hash"]
        result["tip_bits_hex"] = f"{result['bits']:08x}"
        result["tip_time"] = result["time"]
        result["chainwork_since_fork"] = self.work
        return result

    def _locators(self):
        if not self.chain:
            return [COMMON_HASH]
        index = len(self.chain) - 1
        result = []
        step = 1
        while index >= 0:
            result.append(self.chain[index]["hash"])
            if len(result) >= 10:
                step *= 2
            index -= step
        result.append(COMMON_HASH)
        return result

    def _find_parent_index(self, hash_be_hex: str) -> int:
        if hash_be_hex == COMMON_HASH:
            return -1
        # Reorgs ordinarias son superficiales, pero se admite la bifurcación
        # completa desde el checkpoint (sin confiar en la altura del peer).
        for i in range(len(self.chain) - 1, -1, -1):
            if self.chain[i]["hash"] == hash_be_hex:
                return i
        raise ValueError("el peer respondió con headers sin un ancestro conocido")

    def _read_headers(self, socket, broadcaster, deadline: float) -> list[bytes]:
        while time.monotonic() < deadline:
            left = max(0.1, min(8.0, deadline - time.monotonic()))
            command, payload = read_message(socket, broadcaster.params.magic, msg_timeout=left)
            if command == "ping":
                broadcaster._send(socket, "pong", payload)
            elif command == "headers":
                return _unpack_headers(payload)
            # Ignorar inv/feefilter/addr mientras esperamos headers.
        raise TimeoutError("se agotó el tiempo para obtener headers")

    def discover_from_peer(self, peer_str: str, timeout: float = 5.0) -> list[str]:
        """Descubre candidatos con getaddr/addr; no los considera válidos aún."""
        host, port = peer_str.rsplit(":", 1)
        peer = PeerTarget(host=host.strip('[]'), port=int(port))
        broadcaster = BlockBroadcaster(network="tempnet", handshake_timeout=5, timeout=timeout)
        sock = broadcaster.connect(peer)
        requested=False;received=False
        try:
            broadcaster._handshake(sock, peer)
            requested=True
            broadcaster._send(sock, "getaddr")
            deadline = time.monotonic() + timeout
            found = []
            while time.monotonic() < deadline:
                try:
                    command, payload = read_message(
                        sock, broadcaster.params.magic,
                        msg_timeout=max(0.1, deadline - time.monotonic()),
                    )
                except (TimeoutError, socket.timeout):
                    break
                if command == "ping":
                    broadcaster._send(sock, "pong", payload)
                elif command == "addr":
                    found.extend(_unpack_addr(payload))
                    received=True
                    broadcaster._observe(peer,'addr_ok')
                    for candidate in found:
                        candidate_host,candidate_port=candidate.rsplit(':',1)
                        broadcaster._observe(PeerTarget(candidate_host,int(candidate_port)),
                            'peer_seen',sources=[{'type':'peer','value':peer_str}])
                    break
            return list(dict.fromkeys(found))
        finally:
            if requested and not received:
                broadcaster._observe(peer,'addr_fail',status='getaddr sin respuesta válida')
            sock.close()

    def sync_peer(self, peer_str: str, *, max_rounds: int = 120) -> dict:
        host, port = peer_str.rsplit(":", 1)
        peer = PeerTarget(host=host.strip('[]'), port=int(port))
        broadcaster = BlockBroadcaster(network="tempnet", handshake_timeout=5, timeout=10)
        sock = broadcaster.connect(peer)
        try:
            broadcaster._handshake(sock, peer)
            current = list(self.chain)
            for round_idx in range(max_rounds):
                # Los locators se basan en la cadena candidata (no alteramos
                # la cache compartida hasta completar y verificar todo).
                saved = self.chain
                self.chain = current
                locator = self._locators()
                self.chain = saved
                broadcaster._send(sock, "getheaders", _getheaders_payload(locator))
                headers = self._read_headers(sock, broadcaster, time.monotonic() + 15.0)
                if not headers:
                    break
                first_info = parse_header(headers[0])
                if first_info["prev_hash"] == COMMON_HASH:
                    parent_index = -1
                else:
                    parent_index = next((i for i in range(len(current) - 1, -1, -1)
                                         if current[i]["hash"] == first_info["prev_hash"]), None)
                if parent_index is None:
                    raise ValueError("peer no enlazó a ninguno de nuestros locators")
                candidate = current[:parent_index + 1]
                for raw in headers:
                    height = ACTIVATION_HEIGHT + len(candidate) + 1
                    parent_hash = candidate[-1]["hash"] if candidate else COMMON_HASH
                    parent_time = candidate[-1]["time"] if candidate else 0
                    if height == ACTIVATION_HEIGHT + 1:
                        parsed = parse_header(raw)
                        if parsed["hash"] != FIRST_HASH or parsed["prev_hash"] != COMMON_HASH:
                            raise ValueError(f"primer bloque no corresponde a tempnet FABLOUS 2026: recibido={parsed['hash']} esperado={FIRST_HASH}")
                        # La primera cabecera conocida es un checkpoint verificado:
                        # no contamos con el tiempo de su padre para la DAA aquí.
                        parsed = validate_header(raw, parent_height=ACTIVATION_HEIGHT,
                                                 parent_hash=COMMON_HASH, parent_time=0,
                                                 enforce_diff=False)
                    else:
                        parsed = validate_header(raw, parent_height=height - 1,
                                                 parent_hash=parent_hash, parent_time=parent_time)
                        if len(candidate) >= 11:
                            mtp = sorted(e["time"] for e in candidate[-11:])[5]
                            if parsed["time"] <= mtp:
                                raise ValueError("cabecera con timestamp <= MTP del padre")
                    parsed["height"] = height
                    candidate.append(parsed)
                current = candidate
                if len(headers) < 2000:
                    break
            else:
                raise RuntimeError("límite de rondas P2P alcanzado; no se utilizará un tip incompleto")
            if not current:
                raise RuntimeError("peer sin bloques específicos de tempnet")
            total_work = sum(block_work(x["bits"]) for x in current)
            if total_work > self.work or (total_work == self.work and len(current) > len(self.chain)):
                self.chain = current
                self.work = total_work
            self.log(f"[tempnet:p2p] {peer_str}: altura={current[-1]['height']} "
                     f"cabeceras={len(current)} rondas={round_idx + 1} "
                     f"mejor={self.tip['tip_height']}")
            # Evidencia por fuente: no inferimos aceptación del bloque completo.
            self.log(f"[tempnet:p2p-observation] peer={peer_str} "
                     f"candidate_height={current[-1]['height']} "
                     f"candidate_hash={current[-1]['hash']} "
                     f"candidate_prev_hash={current[-1]['prev_hash']} "
                     f"candidate_chainwork={total_work} "
                     f"cache_height={self.tip['tip_height']} "
                     f"cache_hash={self.tip['tip_hash_hex']} "
                     f"cache_chainwork={self.work} "
                     f"rounds={round_idx + 1}")
            broadcaster._observe(peer,'headers_observed',details={
                'height':current[-1]['height'],'hash':current[-1]['hash'],
                'check':'checkpoint_pow_difficulty','full_consensus':False})
            broadcaster._observe(peer,'chain_compatible',status='checkpoint_pow_difficulty')
            return {"peer": peer_str, "height": current[-1]["height"],
                    "hash": current[-1]["hash"], "work": total_work}
        except Exception as exc:
            if 'primer bloque no corresponde' in str(exc):
                broadcaster._observe(peer,'chain_incompatible',status=str(exc)[:250])
            raise
        finally:
            sock.close()

    def sync(self) -> dict:
        errors = []
        successes = []
        for peer in self.peers:
            if peer in self._wrong_chain_peers:
                continue
            try:
                successes.append(self.sync_peer(peer))
            except Exception as e:
                errors.append(f"{peer}: {e}")
                if "primer bloque no corresponde" in str(e):
                    self._wrong_chain_peers.add(peer)
                self.log(f"[tempnet:p2p] peer descartado {peer}: {e}")
        if not successes:
            raise RuntimeError("No se pudo sincronizar tempnet mediante P2P: " + "; ".join(errors))

        # Consultamos el directorio descentralizado que ofrecen los propios
        # peers. No confiamos en sus direcciones sin verificar las cabeceras.
        known_hosts = {x["peer"].rsplit(":", 1)[0] for x in successes}
        # Un watch de 5 s no debe pedir getaddr en cada vuelta: los peers
        # publican muy pocos candidatos y no tiene sentido saturarlos.
        if (self.allow_discovery and len(known_hosts) < 2 and
                time.monotonic() - self._last_discovery_monotonic >= 120.0):
            self._last_discovery_monotonic = time.monotonic()
            existing = set(self.peers)
            candidates = []
            for item in successes:
                try:
                    got = self.discover_from_peer(item["peer"])
                    self.log(f"[tempnet:discovery] {item['peer']}: {len(got)} candidatos por getaddr")
                    candidates.extend(got)
                except Exception as e:
                    self.log(f"[tempnet:discovery] getaddr falló con {item['peer']}: {e}")
            for candidate in dict.fromkeys(candidates):
                if candidate in existing or candidate in self._wrong_chain_peers:
                    continue
                if candidate.rsplit(":", 1)[0] in known_hosts:
                    continue
                # Límite de conexiones activas nuevas por sincronización.
                if len(existing) >= len(PEERS) + 16:
                    break
                existing.add(candidate)
                self.peers = tuple(self.peers) + (candidate,)
                try:
                    entry = self.sync_peer(candidate)
                    successes.append(entry)
                    known_hosts.add(candidate.rsplit(":", 1)[0])
                    if len(known_hosts) >= 2:
                        break
                except Exception as e:
                    errors.append(f"{candidate}: {e}")
                    if "primer bloque no corresponde" in str(e):
                        self._wrong_chain_peers.add(candidate)
                    self.log(f"[tempnet:discovery] candidato descartado {candidate}: {e}")
        result = self.tip
        result["peers_ok"] = [x["peer"] for x in successes]
        self.last_peers_ok = result["peers_ok"]
        result["errors"] = errors
        result["peer_tips"] = successes
        return result
