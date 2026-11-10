"""Diagnóstico observacional de cabeceras por peer para FABLOUS Tempnet.

Se consulta desde el bloque PADRE, en una conexión P2P separada por peer.
No altera la cadena en memoria del minero ni determina validez de UTXO,
aceptación del bloque completo o estado definitivo de consenso.
Los resultados son observaciones, no veredictos.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import time
from typing import Callable, Sequence

from broadcast import BlockBroadcaster, PeerTarget, read_message
from fablous.consensus import parse_header
from fablous.headers import _getheaders_payload, _unpack_headers


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def probe_peer_headers(peer_str: str, parent_hash: str, *, timeout: float = 5.0) -> dict:
    """Devuelve cabeceras recibidas al pedir getheaders desde el PADRE.

    Una respuesta vacía no se interpreta como rechazo ni aceptación: solo
    consta que ese peer devolvió 0 encabezados para el locator solicitado.
    """
    result = {
        "peer": peer_str, "started_utc": utc_now(), "locator_parent": parent_hash,
        "status": "error", "stage": "connect", "response_headers": None,
        "headers": [], "error": None,
    }
    started = time.monotonic()
    sock = None
    try:
        host, port = peer_str.rsplit(":", 1)
        broadcaster = BlockBroadcaster(network="tempnet", handshake_timeout=timeout, timeout=timeout)
        peer = PeerTarget(host=host, port=int(port))
        sock = broadcaster.connect(peer)
        result["stage"] = "handshake"
        broadcaster._handshake(sock, peer)
        result["stage"] = "getheaders"
        broadcaster._send(sock, "getheaders", _getheaders_payload([parent_hash]))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            command, payload = read_message(
                sock, broadcaster.params.magic,
                msg_timeout=max(0.1, deadline - time.monotonic()),
            )
            if command == "ping":
                broadcaster._send(sock, "pong", payload)
                continue
            if command != "headers":
                # Se conserva el comando ignorado; no se lo toma como evidencia
                # de que el peer aceptó o rechazó el bloque.
                result.setdefault("other_commands", []).append(command)
                continue
            headers = _unpack_headers(payload)
            result["response_headers"] = len(headers)
            # El mensaje P2P puede contener como máximo 2.000 cabeceras.
            # Si llega al límite, ignoramos si hay más: no afirmamos conocer
            # la punta final del peer.
            result["may_have_more_headers"] = len(headers) == 2000
            result["headers"] = [
                {
                    "hash": (hinfo := parse_header(raw))["hash"],
                    "prev_hash": hinfo["prev_hash"],
                    "nBits": f"{hinfo['bits']:08x}",
                    "ntime": hinfo["time"],
                    "nonce": hinfo["nonce"],
                } for raw in headers
            ]
            result["status"] = "response"
            result["stage"] = "completed"
            break
        else:
            raise TimeoutError("sin mensaje headers dentro del plazo de observación")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if sock is not None:
            try: sock.close()
            except Exception: pass
        result["completed_utc"] = utc_now()
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
    return result


def observe_peers(peers: Sequence[str], parent_hash: str, *,
                  observer: Callable = probe_peer_headers, max_workers: int = 3) -> list[dict]:
    """Consulta peers concurrentemente y devuelve sus observaciones por separado."""
    unique_peers = list(dict.fromkeys(peers))
    if not unique_peers:
        return []
    observations = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique_peers))) as executor:
        futures = {executor.submit(observer, peer, parent_hash): peer for peer in unique_peers}
        for future in as_completed(futures):
            peer = futures[future]
            try:
                observations.append(future.result())
            except Exception as exc:
                observations.append({"peer": peer, "status": "error",
                                     "locator_parent": parent_hash,
                                     "error": f"{type(exc).__name__}: {exc}",
                                     "headers": [], "response_headers": None})
    return observations


def format_peer_observation(observation: dict, *, block_hash: str = "", height: int | None = None) -> list[str]:
    """Presenta hechos con procedencia, sin clasificar aceptación del bloque."""
    o=observation
    prefix=(f"[tempnet:peer-observation] block_hash={block_hash or 'no_disponible'} "
            f"height={height if height is not None else 'no_disponible'} "
            f"peer={o['peer']}")
    lines=[
        f"{prefix} utc_start={o.get('started_utc', 'no_disponible')} "
        f"utc_end={o.get('completed_utc','no_disponible')} "
        f"duration_ms={o.get('duration_ms','no_disponible')} "
        f"locator_parent={o['locator_parent']} status={o['status']} "
        f"stage={o.get('stage','no_disponible')} "
        f"headers_count={o.get('response_headers','no_respuesta')} "
        f"more_headers_possible={o.get('may_have_more_headers', 'desconocido')} "
        f"error={o.get('error')!r}"
    ]
    for i, h in enumerate(o.get('headers', [])):
        lines.append(f"{prefix} header[{i}] hash={h['hash']} "
                     f"prev_hash={h['prev_hash']} nBits={h['nBits']} "
                     f"ntime={h['ntime']} nonce={h['nonce']}")
    for cmd in o.get('other_commands', []):
        lines.append(f"{prefix} other_command={cmd}")
    return lines
