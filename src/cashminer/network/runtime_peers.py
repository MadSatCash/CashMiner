"""Eventos estructurados del motor hacia SQLite, con compatibilidad de logs.

La cola acotada y el escritor separado evitan esperar a SQLite desde el lector.
No interpreta recibir un bloque como validación completa de consenso.
"""
from __future__ import annotations

import queue
import json
import logging
import sqlite3
from datetime import datetime, timezone
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cashminer.config import network_db_path
from cashminer.network.endpoints import split_endpoint, endpoint
from cashminer.network.peer_store import PeerStore

PEER = r'(?P<peer>(?:\[[0-9a-fA-F:]+\]|(?:\d{1,3}\.){3}\d{1,3}):\d{1,5})'
EVENT_PREFIX='[cashminer-peer-event] '
EVENT_LINE=re.compile(r'^(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?\[cashminer-peer-event\] ')


def is_peer_event_line(line):
    return bool(EVENT_LINE.match(line))
TIP = re.compile(r'\[tempnet:p2p-observation\]\s+peer=' + PEER + r'\s+candidate_height=(?P<height>\d+)\s+candidate_hash=(?P<hash>[0-9a-fA-F]{64})')
PEER_REJECT = re.compile(r'\[tempnet:p2p\]\s+peer descartado\s+' + PEER + r':\s+(?P<error>.*)')
BROADCAST = re.compile(r'\[broadcast:(?P<state>OK|FAIL)\]\s+' + PEER + r'\s+->\s+(?P<detail>.*)')
HEADERS = re.compile(r'\[tempnet:peer-observation\]\s+block_hash=(?P<hash>[0-9a-fA-F]{64})\s+height=(?P<height>\d+)\s+peer=' + PEER + r'.*?\s+status=(?P<status>\w+)\s+stage=(?P<stage>\w+)(?:\s+headers_count=(?P<count>\d+))?')

@dataclass(frozen=True)
class PeerObservation:
    peer: str
    kind: str
    result: str = ''
    details: dict | None = None
    timestamp: str | None = None


def parse_peer_event(line, network):
    packet=json.JSONDecoder().raw_decode(line.split(EVENT_PREFIX,1)[1])[0]
    if not isinstance(packet,dict) or packet.get('schema')!=1:
        raise ValueError('Formato de evento P2P inválido')
    event_network=packet.get('network')
    if event_network=='testnet':event_network='testnet3'
    if event_network=='tempnet':event_network='tempnet_fablous_2026'
    if event_network!=network:raise ValueError('Evento P2P de otra red')
    peer=endpoint(packet['ip'],packet['port'])
    split_endpoint(peer)  # Validate the port as well as IPv4/IPv6.
    when=datetime.fromisoformat(packet['ts'])
    if when.tzinfo is None:raise ValueError('Evento sin zona horaria')
    stamp=when.astimezone(timezone.utc).isoformat(timespec='microseconds')
    kind=packet['kind']
    details=dict(packet.get('details') or {})
    result=str(packet.get('status') or '')[:250]
    if kind in ('peer_seen','peer_selected'):
        sources=packet.get('sources') or []
        if not isinstance(sources,list):raise ValueError('Fuentes inválidas')
        details['sources']=sources
        if kind=='peer_seen' and any(isinstance(s,dict) and s.get('type')=='mining_selection' for s in sources):
            kind='peer_selected'  # Read old selection packets without fabricating activity.
    elif kind=='handshake_ok':
        for key in ('services','protocol_version','user_agent'):
            if packet.get(key) is not None:details[key]=packet[key]
    elif kind=='broadcast_result':
        text=str(packet.get('detail') or '')
        lower=text.lower()
        details['response']=text[:320]
        if packet.get('ok') is True:
            kind='broadcast_getdata' if packet.get('block_sent') is True or any(x in lower for x in ('getdata','pidió el bloque','pidio el bloque','requested block','requested the block')) else 'broadcast_headers_ok'
            result='block_sent_after_getdata' if kind=='broadcast_getdata' else 'announced_without_getdata'
        else:
            kind='broadcast_timeout' if ('timeout' in lower or 'timed out' in lower) else 'broadcast_reject' if ('reject' in lower or 'rechaz' in lower) else 'broadcast_failed'
            result=text[:250]
    if kind not in ('peer_seen','peer_selected','connect_attempt','tcp_ok','tcp_fail','handshake_ok','handshake_fail',
                    'addr_ok','addr_fail','broadcast_attempt','broadcast_getdata','broadcast_headers_ok',
                    'broadcast_timeout','broadcast_reject','broadcast_failed','headers_observed','headers_response',
                    'chain_compatible','chain_incompatible'):
        raise ValueError('Tipo de evento P2P desconocido')
    observations=[PeerObservation(peer,kind,result,details,stamp)]
    if packet.get('kind')=='broadcast_result' and packet.get('block_sent') is True and packet.get('ok') is not True:
        observations.insert(0,PeerObservation(peer,'broadcast_getdata','block_sent_before_final_failure',details,stamp))
    return observations


def parse_runtime_line(line: str) -> list[PeerObservation]:
    """Devuelve hechos observados; no deduce aceptaciones de bloques.

    Un `broadcast:OK` puede ser sólo un anuncio, no prueba de consenso.
    Un peer que informa cabeceras permitió handshake, pero no implica que todo
    el bloque haya sido validado. La relación con cadena la evalúa el motor.
    """
    if m := TIP.search(line):
        info = {'height': int(m['height']), 'hash': m['hash'].lower(), 'origin': 'miner_runtime'}
        return [PeerObservation(m['peer'], 'connect_attempt'),
                PeerObservation(m['peer'], 'tcp_ok'),
                PeerObservation(m['peer'], 'handshake_ok'),
                PeerObservation(m['peer'], 'headers_observed', 'tip_reported', info),
                PeerObservation(m['peer'], 'chain_compatible', 'header_cache_accepted')]
    if m := PEER_REJECT.search(line):
        err = m['error']
        detail = {'origin': 'miner_runtime', 'error': err[:320]}
        lower = err.lower()
        if 'primer bloque no corresponde' in lower or 'génesis' in lower or 'genesis' in lower:
            event = 'chain_incompatible'
        elif 'handshake' in lower or 'magic' in lower:
            event = 'handshake_fail'
        else:
            event = 'tcp_fail'
        return [PeerObservation(m['peer'], 'connect_attempt'),
                PeerObservation(m['peer'], event, err[:100], detail)]
    if m := BROADCAST.search(line):
        lower = m['detail'].lower()
        details = {'origin': 'miner_runtime', 'response': m['detail'][:320]}
        events = [PeerObservation(m['peer'], 'broadcast_attempt')]
        if m['state'] == 'OK':
            kind = 'broadcast_getdata' if 'pidió el bloque y fue enviado' in lower else 'broadcast_headers_ok'
            result = 'block_sent_after_getdata' if kind == 'broadcast_getdata' else 'announced_without_getdata'
        else:
            kind = 'broadcast_timeout' if 'timeout' in lower else 'broadcast_reject' if ('rechaz' in lower or lower.startswith('reject')) else 'broadcast_failed'
            result = m['detail'][:100]
        events.append(PeerObservation(m['peer'], kind, result, details))
        return events
    if m := HEADERS.search(line):
        details = {'origin': 'miner_runtime', 'block_hash': m['hash'],
                   'height': int(m['height']), 'stage': m['stage'],
                   'headers_count': int(m['count']) if m['count'] is not None else None}
        if m['status'] == 'response':
            return [PeerObservation(m['peer'], 'headers_response', 'response', details)]
        return [PeerObservation(m['peer'], 'headers_response', m['status'], details)]
    return []


class RuntimePeerRecorder:
    """Acota memoria, no bloquea la salida del motor y serializa operaciones.

    No registra eventos fabricados al reproducir un log salvo uso explícito.
    Cada tanda se guarda en una sola transacción mediante PeerStore.record_many.
    """
    def __init__(self, *, root: Path | None = None, max_mib: int = 100,
                 queue_size: int = 2000, structured: bool = False):
        self.root = root
        self.max_mib = max_mib
        self.events = queue.Queue(maxsize=queue_size)
        self.dropped = 0
        self.failures = 0
        self.invalid = 0
        self.last_error = ''
        self.structured = structured
        self._thread = threading.Thread(target=self._run, daemon=True, name='CashMiner-peer-recorder')
        self._thread.start()

    def observe(self, network: str, line: str):
        if is_peer_event_line(line):
            try:observations=parse_peer_event(line,network)
            except (ValueError,KeyError,TypeError,OverflowError):
                self.invalid+=1
                return
        else:
            observations = parse_runtime_line(line)
            if self.structured:
                # Only the detailed post-broadcast observer still uses text.
                # Transport, tip/checkpoint and broadcast facts have one owner.
                observations=[o for o in observations if o.kind=='headers_response']
        if not observations:
            return
        # La red se captura por evento para evitar mezclar bases entre sesiones.
        try:
            self.events.put_nowait((network, observations))
        except queue.Full:
            self.dropped += len(observations)

    def _run(self):
        stores = {}
        while True:
            item = self.events.get()
            try:
                if item is None:
                    return
                network, observations = item
                if network not in stores:
                    stores[network] = PeerStore(network_db_path(network, self.root), max_mib=self.max_mib)
                store = stores[network]
                for attempt in range(3):
                    try:
                        store.record_many(observations)
                        break
                    except sqlite3.OperationalError as exc:
                        if attempt==2 or not any(x in str(exc).lower() for x in ('locked','busy')):raise
                        time.sleep(.05*(attempt+1))
            except Exception as exc:
                # SQLite no debe impedir ni ralentizar los callbacks del minero.
                self.failures += 1
                self.last_error=str(exc)[:250]
                logging.getLogger('cashminer.application').warning('No se guardó una observación P2P del minero: %s',self.last_error)
            finally:
                self.events.task_done()

    def drain(self, timeout: float = 3.0) -> bool:
        end = time.monotonic() + max(0.0, timeout)
        while self.events.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)
        return self.events.unfinished_tasks == 0

    def close(self):
        self.drain()
        try:
            self.events.put_nowait(None)
        except queue.Full:
            return
        self._thread.join(timeout=1)
        if self.dropped or self.invalid or self.failures:
            logging.getLogger('cashminer.application').warning(
                'Registro P2P: descartados=%s inválidos=%s erroresSQLite=%s',
                self.dropped,self.invalid,self.failures)
