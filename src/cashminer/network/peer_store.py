"""SQLite por red. Evidencia de peers, no autoridad de consenso o billetera.

SQLite tiene un único escritor real. Cada operación usa transacciones cortas y
conexiones independientes, aptas para una futura cola de escritor central.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from cashminer.network.endpoints import normalize_ip, split_endpoint
from cashminer.network.scoring import operational_score

SCHEMA_VERSION = 2
COUNTERS = (
    "tcp_ok_count", "tcp_fail_count", "handshake_ok_count", "handshake_fail_count",
    "addr_ok_count", "addr_fail_count", "broadcast_attempt_count",
    "broadcast_headers_ok_count", "broadcast_getdata_count", "broadcast_reject_count",
)
TIMESTAMPS = (
    "first_seen_at", "last_seen_at", "last_attempt_at", "last_tcp_ok_at",
    "last_handshake_ok_at", "last_addr_ok_at", "last_broadcast_attempt_at",
    "last_broadcast_headers_ok_at", "last_broadcast_getdata_at",
)
PEER_FIELDS = (
    "ip", "port", "first_seen_at", "last_seen_at", "last_attempt_at", "last_status",
    "last_tcp_ok_at", "tcp_ok_count", "tcp_fail_count", "last_handshake_ok_at",
    "handshake_ok_count", "handshake_fail_count", "services", "protocol_version",
    "user_agent", "last_addr_ok_at", "addr_ok_count", "addr_fail_count",
    "last_broadcast_attempt_at", "broadcast_attempt_count",
    "last_broadcast_headers_ok_at", "broadcast_headers_ok_count",
    "last_broadcast_getdata_at", "broadcast_getdata_count", "broadcast_reject_count",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class PeerStore:
    def __init__(self, path: str | Path, *, max_mib: int = 100, create: bool = True):
        self.path = Path(path)
        self.max_bytes = max(2, int(max_mib)) * 1024 * 1024
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        first = not self.path.exists()
        with self.connect() as c:
            if first:
                c.execute("PRAGMA auto_vacuum=INCREMENTAL")
                c.execute("PRAGMA journal_mode=WAL")
            else:
                c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS peers (
                ip TEXT NOT NULL, port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
                first_seen_at TEXT, last_seen_at TEXT, last_attempt_at TEXT, last_status TEXT,
                last_tcp_ok_at TEXT, tcp_ok_count INTEGER NOT NULL DEFAULT 0,
                tcp_fail_count INTEGER NOT NULL DEFAULT 0, last_handshake_ok_at TEXT,
                handshake_ok_count INTEGER NOT NULL DEFAULT 0,
                handshake_fail_count INTEGER NOT NULL DEFAULT 0, services INTEGER,
                protocol_version INTEGER, user_agent TEXT, last_addr_ok_at TEXT,
                addr_ok_count INTEGER NOT NULL DEFAULT 0, addr_fail_count INTEGER NOT NULL DEFAULT 0,
                last_broadcast_attempt_at TEXT, broadcast_attempt_count INTEGER NOT NULL DEFAULT 0,
                last_broadcast_headers_ok_at TEXT,
                broadcast_headers_ok_count INTEGER NOT NULL DEFAULT 0,
                last_broadcast_getdata_at TEXT,
                broadcast_getdata_count INTEGER NOT NULL DEFAULT 0,
                broadcast_reject_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (ip, port));
            CREATE TABLE IF NOT EXISTS peer_sources (
                ip TEXT NOT NULL, port INTEGER NOT NULL, source_type TEXT NOT NULL,
                source_value TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL, seen_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (ip, port, source_type, source_value),
                FOREIGN KEY (ip, port) REFERENCES peers(ip, port) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS peer_events (
                event_id INTEGER PRIMARY KEY,
                ip TEXT NOT NULL, port INTEGER NOT NULL, timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL, result TEXT,
                latency_ms REAL, details TEXT,
                FOREIGN KEY (ip, port) REFERENCES peers(ip, port) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_peer_handshake
                ON peers(last_handshake_ok_at);
            CREATE INDEX IF NOT EXISTS idx_peerevents_peer_time
                ON peer_events(ip, port, timestamp);
            CREATE INDEX IF NOT EXISTS idx_peerevents_time ON peer_events(timestamp);
            CREATE TABLE IF NOT EXISTS explorer_cycle_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                started_at TEXT,
                last_completed_at TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS explorer_cycle_queue (
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (ip, port)
            );
            CREATE INDEX IF NOT EXISTS idx_explorer_cycle_pending
                ON explorer_cycle_queue(processed);
            CREATE TABLE IF NOT EXISTS imported_snapshots (
                source_sha256 TEXT NOT NULL, network TEXT NOT NULL, imported_at TEXT NOT NULL,
                rows_imported INTEGER NOT NULL, PRIMARY KEY(source_sha256, network));
            """)
            existing = c.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            version = int(existing[0]) if existing else 1
            if version not in (1, SCHEMA_VERSION):
                raise ValueError("Versión de DB incompatible: " + str(version))
            # Migración no destructiva: versión 1 ya contiene billeteras/historial
            # en otras tablas; jamás reconstruir ni borrar la SQLite existente.
            extra_columns = {
                "last_headers_at": "TEXT", "last_header_height": "INTEGER",
                "last_header_hash": "TEXT", "last_chain_compatible_at": "TEXT",
                "last_chain_incompatible_at": "TEXT", "last_miner_event_at": "TEXT",
                "runtime_event_count": "INTEGER NOT NULL DEFAULT 0",
            }
            actual = {row[1] for row in c.execute("PRAGMA table_info(peers)")}
            for name, sqltype in extra_columns.items():
                if name not in actual:
                    c.execute(f"ALTER TABLE peers ADD COLUMN {name} {sqltype}")
            c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('version',?)", (str(SCHEMA_VERSION),))

    def explorer_cycle_status(self) -> dict:
        """One current cycle + one timestamp; no historical cycle records."""
        with self.connect() as c:
            row=c.execute('SELECT started_at,last_completed_at,active,total FROM explorer_cycle_state WHERE singleton=1').fetchone()
            if row is None:
                return {'started_at':None,'last_completed_at':None,'active':False,'total':0,'processed':0}
            done=c.execute('SELECT COUNT(*) FROM explorer_cycle_queue WHERE processed=1').fetchone()[0] if row['active'] else 0
            return {'started_at':row['started_at'],'last_completed_at':row['last_completed_at'],
                    'active':bool(row['active']),'total':int(row['total']),'processed':done}

    def explorer_begin_cycle(self) -> dict:
        """Freeze current candidates once, after DNS/bootstrap discovery.

        Unfinished cycles survive restarts and are never overwritten by new DNS
        discoveries. The queue refers to existing peer identities only.
        """
        with self.connect() as c:
            state=c.execute('SELECT active FROM explorer_cycle_state WHERE singleton=1').fetchone()
            if state and state[0]:
                return self._cycle_status_in_connection(c)
            c.execute('DELETE FROM explorer_cycle_queue')
            c.execute("""INSERT INTO explorer_cycle_queue(ip,port)
                SELECT ip,port FROM peers ORDER BY
                CASE WHEN last_attempt_at IS NULL THEN 0 ELSE 1 END,
                COALESCE(last_attempt_at,'') ASC, ip, port""")
            count=c.execute('SELECT COUNT(*) FROM explorer_cycle_queue').fetchone()[0]
            started=utcnow()
            c.execute("""INSERT INTO explorer_cycle_state(singleton,started_at,active,total)
                VALUES(1,?,1,?) ON CONFLICT(singleton) DO UPDATE SET
                started_at=excluded.started_at,active=1,total=excluded.total""",(started,count))
            return self._cycle_status_in_connection(c)

    @staticmethod
    def _cycle_status_in_connection(c):
        row=c.execute('SELECT started_at,last_completed_at,active,total FROM explorer_cycle_state WHERE singleton=1').fetchone()
        processed=c.execute('SELECT COUNT(*) FROM explorer_cycle_queue WHERE processed=1').fetchone()[0] if row and row['active'] else 0
        return {'started_at':row['started_at'],'last_completed_at':row['last_completed_at'],
                'active':bool(row['active']),'total':int(row['total']),'processed':processed}

    def explorer_pending_batch(self, limit: int) -> list[tuple[str,int]]:
        with self.connect() as c:
            return [(r['ip'],int(r['port'])) for r in c.execute(
                'SELECT ip,port FROM explorer_cycle_queue WHERE processed=0 ORDER BY rowid LIMIT ?',
                (int(limit),))]

    def explorer_mark_attempted(self, ip: str, port: int) -> None:
        with self.connect() as c:
            c.execute('UPDATE explorer_cycle_queue SET processed=1 WHERE ip=? AND port=?',(ip,int(port)))

    def explorer_complete_cycle(self) -> str:
        """Atomically commit the scheduling timestamp and discard all work rows."""
        with self.connect() as c:
            active=c.execute('SELECT active FROM explorer_cycle_state WHERE singleton=1').fetchone()
            if not active or not active[0]:
                raise ValueError('No hay un ciclo de exploración activo')
            if c.execute('SELECT EXISTS(SELECT 1 FROM explorer_cycle_queue WHERE processed=0)').fetchone()[0]:
                raise ValueError('Ciclo incompleto: quedan peers pendientes')
            stamp=utcnow()
            c.execute('UPDATE explorer_cycle_state SET active=0,last_completed_at=? WHERE singleton=1',(stamp,))
            c.execute('DELETE FROM explorer_cycle_queue')
            return stamp

    def add_peer(self, ip: str, port: int, *, source_type: str | None = None,
                 source_value: str | None = None, seen_at: str | None = None):
        ip = normalize_ip(ip)
        port = int(port)
        ts = seen_at or utcnow()
        with self.connect() as c:
            c.execute("""INSERT INTO peers(ip,port,first_seen_at,last_seen_at)
                         VALUES(?,?,?,?) ON CONFLICT(ip,port) DO UPDATE SET
                         first_seen_at = COALESCE(peers.first_seen_at,excluded.first_seen_at),
                         last_seen_at = CASE WHEN excluded.last_seen_at > COALESCE(peers.last_seen_at,'')
                              THEN excluded.last_seen_at ELSE peers.last_seen_at END""",
                      (ip, port, ts, ts))
            if source_type and source_value:
                self._add_source(c, ip, port, source_type, source_value, ts)

    @staticmethod
    def _add_source(c, ip, port, kind, value, ts):
        c.execute("""INSERT INTO peer_sources(ip,port,source_type,source_value,first_seen_at,last_seen_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(ip,port,source_type,source_value)
                     DO UPDATE SET last_seen_at=excluded.last_seen_at,
                         seen_count=peer_sources.seen_count+1""", (ip, port, str(kind)[:40], str(value)[:256], ts, ts))

    @staticmethod
    def _record_in_connection(c, ip: str, port: int, kind: str, *,
                              ts: str, result: str | None = None,
                              latency_ms: float | None = None,
                              details: dict | None = None, origin: str | None = None,
                              include_detail: bool = True):
        # El evento crudo y el estado derivado se guardan separadamente.
        sources=(details or {}).get('sources',[])
        if kind=='peer_selected' or (kind=='peer_seen' and any(
                isinstance(source,dict) and source.get('type')=='mining_selection' for source in sources)):
            # Selection is a local decision, not evidence of network activity.
            # Even a new candidate must retain unknown activity dates/counters.
            c.execute('INSERT OR IGNORE INTO peers(ip,port) VALUES (?,?)',(ip,port))
            for source in sources:
                if isinstance(source,dict) and source.get('type')=='mining_selection' and source.get('value'):
                    PeerStore._add_source(c,ip,port,'mining_selection',source['value'],ts)
            if include_detail:
                data=dict(details or {})
                if origin:data['origin']=origin
                payload=json.dumps(data,sort_keys=True,ensure_ascii=False)[:700] if data else None
                c.execute('''INSERT INTO peer_events(ip,port,timestamp,event_type,result,latency_ms,details)
                    VALUES(?,?,?,?,?,?,?)''',(ip,port,ts,'peer_selected',result,latency_ms,payload))
            return
        fieldmap = {
            "peer_seen": (None, None),
            "connect_attempt": ("last_attempt_at", None),
            "tcp_ok": ("last_tcp_ok_at", "tcp_ok_count"),
            "tcp_fail": (None, "tcp_fail_count"),
            "handshake_ok": ("last_handshake_ok_at", "handshake_ok_count"),
            "handshake_fail": (None, "handshake_fail_count"),
            "addr_ok": ("last_addr_ok_at", "addr_ok_count"),
            "addr_fail": (None, "addr_fail_count"),
            "broadcast_attempt": ("last_broadcast_attempt_at", "broadcast_attempt_count"),
            "broadcast_headers_ok": ("last_broadcast_headers_ok_at", "broadcast_headers_ok_count"),
            "broadcast_getdata": ("last_broadcast_getdata_at", "broadcast_getdata_count"),
            "broadcast_reject": (None, "broadcast_reject_count"),
            "broadcast_timeout": (None, None),
            "broadcast_failed": (None, None),
            "headers_response": (None, None),
            "headers_observed": ("last_headers_at", None),
            "chain_incompatible": ("last_chain_incompatible_at", None),
            "chain_compatible": ("last_chain_compatible_at", None),
        }
        if kind not in fieldmap:
            raise ValueError(f"Tipo de evento desconocido: {kind}")
        c.execute("INSERT OR IGNORE INTO peers(ip,port,first_seen_at,last_seen_at) VALUES (?,?,?,?)",
                  (ip, port, ts, ts))
        timestamp_field, counter = fieldmap[kind]
        changes = ["last_status=?", "last_seen_at=CASE WHEN ? > COALESCE(last_seen_at,'') THEN ? ELSE last_seen_at END",
                   "first_seen_at=COALESCE(first_seen_at,?)"]
        params = [str(result or kind)[:100], ts, ts, ts]
        if timestamp_field:
            changes.append(f"{timestamp_field}=CASE WHEN ? > COALESCE({timestamp_field},'') THEN ? ELSE {timestamp_field} END")
            params.extend((ts,ts))
        if counter:
            changes.append(f"{counter}={counter}+1")
        if kind in ("connect_attempt", "tcp_fail"):
            changes.append("last_attempt_at=CASE WHEN ? > COALESCE(last_attempt_at,'') THEN ? ELSE last_attempt_at END")
            params.extend((ts,ts))
        if kind == "handshake_ok" and details:
            for field in ("services", "protocol_version", "user_agent"):
                if details.get(field) is not None:
                    changes.append(f"{field}=?")
                    params.append(str(details[field])[:160] if field == "user_agent" else int(details[field]))
        if kind == "broadcast_getdata":
            changes.extend(["broadcast_headers_ok_count=broadcast_headers_ok_count+1",
                "last_broadcast_headers_ok_at=CASE WHEN ? > COALESCE(last_broadcast_headers_ok_at,'') THEN ? ELSE last_broadcast_headers_ok_at END"])
            params.extend((ts,ts))
        if kind == "headers_observed" and details:
            if details.get('height') is not None:
                changes.append("last_header_height=CASE WHEN ? >= COALESCE(last_headers_at,'') THEN ? ELSE last_header_height END")
                params.extend((ts,int(details['height'])))
            if details.get('hash'):
                changes.append("last_header_hash=CASE WHEN ? >= COALESCE(last_headers_at,'') THEN ? ELSE last_header_hash END")
                params.extend((ts,str(details['hash'])[:64]))
        if origin == 'miner_runtime':
            changes.extend(["last_miner_event_at=CASE WHEN ? > COALESCE(last_miner_event_at,'') THEN ? ELSE last_miner_event_at END", "runtime_event_count=runtime_event_count+1"])
            params.extend((ts,ts))
        c.execute(f"UPDATE peers SET {', '.join(changes)} WHERE ip=? AND port=?",
                  (*params, ip, int(port)))
        if kind == 'peer_seen' and details:
            for source in details.get('sources',[]):
                if isinstance(source,dict) and source.get('type') and source.get('value'):
                    PeerStore._add_source(c,ip,port,source['type'],source['value'],ts)
        if origin == 'miner_runtime':
            c.execute("""INSERT INTO peer_sources
                (ip,port,source_type,source_value,first_seen_at,last_seen_at)
                VALUES (?,?,'runtime','minería',?,?)
                ON CONFLICT(ip,port,source_type,source_value)
                DO UPDATE SET last_seen_at=excluded.last_seen_at""", (ip,port,ts,ts))
        if include_detail:
            data = dict(details or {})
            if origin:
                data['origin'] = origin
            payload = json.dumps(data, sort_keys=True, ensure_ascii=False)[:700] if data else None
            c.execute("""INSERT INTO peer_events
                (ip,port,timestamp,event_type,result,latency_ms,details)
                VALUES(?,?,?,?,?,?,?)""",
                (ip,port,ts,kind,result,latency_ms,payload))

    def record(self, ip: str, port: int, kind: str, *, result: str | None = None,
               latency_ms: float | None = None, details: dict | None = None):
        ip = normalize_ip(ip)
        ts = utcnow()
        with self.connect() as c:
            self._record_in_connection(c,ip,int(port),kind,ts=ts,result=result,
                latency_ms=latency_ms,details=details,
                include_detail=self.size_bytes() < self.max_bytes * 0.95)

    def record_many(self, observations, *, origin: str = 'miner_runtime'):
        """Una tanda de eventos del runtime, en una transacción SQLite corta.

        La cola de la interfaz desacopla escritura y minería. Si se supera el
        presupuesto, siguen actualizándose agregados pero no crece peer_events.
        """
        if not observations:
            return
        ts = utcnow()
        with self.connect() as c:
            include_detail = self.size_bytes() < self.max_bytes * 0.95
            for obs in observations:
                ip, port = split_endpoint(obs.peer)
                self._record_in_connection(c,ip,port,obs.kind,ts=getattr(obs,'timestamp',None) or ts,
                    result=obs.result,details=obs.details,origin=origin,
                    include_detail=include_detail)

    def count(self) -> int:
        with self.connect() as c:
            return c.execute("SELECT count(*) FROM peers").fetchone()[0]

    def counts(self) -> dict[str, int]:
        with self.connect() as c:
            return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                    for t in ("peers", "peer_sources", "peer_events")}

    def peers(self, limit: int = 20, *, sort_by_score: bool = True):
        with self.connect() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM peers")]
        if sort_by_score:
            rows.sort(key=operational_score, reverse=True)
        return rows[:max(0,int(limit))]

    def get(self, ip, port):
        with self.connect() as c:
            r = c.execute("SELECT * FROM peers WHERE ip=? AND port=?", (normalize_ip(ip), int(port))).fetchone()
            return dict(r) if r else None

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in
                   (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")) if p.exists())

    def integrity(self) -> dict:
        with self.connect() as c:
            check = c.execute("PRAGMA quick_check").fetchone()[0]
            fk = len(c.execute("PRAGMA foreign_key_check").fetchall())
        return {"quick_check": check, "foreign_key_errors": fk, "size_bytes": self.size_bytes()}

    def cleanup(self, *, days: int = 30, stale_days: int = 365, max_events: int = 10000) -> dict:
        """Elimina detalle viejo, no el historial agregado; nunca toca wallets.

        No se borran peers con handshake exitoso, ni recientes, ni las seeds.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1,days))).isoformat()
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(30,stale_days))).isoformat()
        with self.connect() as c:
            initial_events = c.execute("SELECT count(*) FROM peer_events").fetchone()[0]
            c.execute("DELETE FROM peer_events WHERE timestamp<?", (cutoff,))
            c.execute("""DELETE FROM peer_events WHERE event_id IN
                (SELECT event_id FROM peer_events ORDER BY timestamp DESC LIMIT -1 OFFSET ?)""",
                      (max(100,int(max_events)),))
            # Peers que nunca funcionaron y llevan mucho tiempo sin verse.
            c.execute("""DELETE FROM peers WHERE handshake_ok_count=0 AND
                       last_seen_at < ? AND
                       NOT EXISTS (SELECT 1 FROM peer_sources s
                          WHERE s.ip=peers.ip AND s.port=peers.port
                          AND s.source_type IN ('manual','seed','bootstrap'))""", (stale_cutoff,))
            removed_peers = c.execute("SELECT changes()").fetchone()[0]
            kept_events = c.execute("SELECT count(*) FROM peer_events").fetchone()[0]
            c.execute("PRAGMA incremental_vacuum(100)")
        # Si otro proceso mantiene WAL en uso, puede no truncar inmediatamente.
        with self.connect() as c:
            c.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        return {"events_removed": initial_events-kept_events,
                "peers_removed": removed_peers, "bytes_after": self.size_bytes(),
                "budget_bytes": self.max_bytes}
