"""Derived peer references, never a new source of network observations.

One small SQLite per network. A transaction replaces the current list, so
readers see either generation and interrupted writers leave the old list.
Calculation timestamps are informational: no age-based expiry/invalidation.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from cashminer.config import network_db_path
from cashminer.network.endpoints import endpoint, split_endpoint
from cashminer.network.networks import NETWORKS
from cashminer.network.policy import HEALTHY_FLOOR, rank_mining_candidates, select_ranked_peers

FORMAT_VERSION = 1
POLICY_VERSION = 'healthy-flaky-v1'
# Background update frequency, not a validity deadline for saved results.
RANK_INTERVAL_SECONDS = 300
LOG = logging.getLogger('cashminer.application.peer_rankings')


def ranking_path(root: Path, network: str) -> Path:
    if network not in NETWORKS:raise ValueError('Red desconocida')
    return Path(root)/'rankings'/(network+'.sqlite')


def _readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)
    db.row_factory = sqlite3.Row
    return db


def read_peer_snapshot(root: Path, network: str):
    # Never initialize, migrate or write the source database in this process.
    with closing(_readonly(network_db_path(network,root))) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='peers'").fetchone():
            return []
        return [dict(r) for r in db.execute('SELECT * FROM peers')]


def _publish(path, network, healthy, flaky, calculated_at):
    with closing(sqlite3.connect(path, timeout=.5)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        try:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] != FORMAT_VERSION:
                db.execute('DROP TABLE IF EXISTS rank_entries')
                db.execute('DROP TABLE IF EXISTS rank_meta')
            db.execute('''CREATE TABLE IF NOT EXISTS rank_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), network TEXT NOT NULL,
                calculated_at TEXT NOT NULL, policy TEXT NOT NULL,
                healthy INTEGER NOT NULL, flaky INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS rank_entries (
                position INTEGER PRIMARY KEY, ip TEXT NOT NULL, port INTEGER NOT NULL,
                UNIQUE(ip,port))''')
            db.execute('DELETE FROM rank_entries')
            db.executemany('INSERT INTO rank_entries VALUES(?,?,?)',
                ((i,r['ip'],int(r['port'])) for i,r in enumerate([*healthy,*flaky])))
            db.execute('INSERT OR REPLACE INTO rank_meta VALUES(1,?,?,?,?,?)',
                (network,calculated_at,POLICY_VERSION,len(healthy),len(flaky)))
            db.execute(f'PRAGMA user_version={FORMAT_VERSION}')
            db.commit()
        except BaseException:
            db.rollback()
            raise


def build_ranking(root: Path, network: str, *, now=None):
    started=time.perf_counter()
    rows=read_peer_snapshot(root,network)
    loaded=time.perf_counter()
    now=now or datetime.now(timezone.utc)
    healthy,flaky=rank_mining_candidates(rows,now=now)
    ordered=time.perf_counter()
    path=ranking_path(root,network)
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        _publish(path,network,healthy,flaky,now.isoformat())
    except sqlite3.DatabaseError as exc:
        # Only an unreadable derived cache may be discarded. Busy/permission/
        # programming errors must preserve the last committed generation.
        if getattr(exc,'sqlite_errorcode',None) not in (sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB):raise
        path.unlink()
        for suffix in ('-wal','-shm'):
            Path(str(path)+suffix).unlink(missing_ok=True)
        _publish(path,network,healthy,flaky,now.isoformat())
    finished=time.perf_counter()
    return dict(network=network,rows=len(rows),eligible=len(healthy)+len(flaky),
        read_ms=(loaded-started)*1000,rank_ms=(ordered-loaded)*1000,
        publish_ms=(finished-ordered)*1000,total_ms=(finished-started)*1000)


def read_ranking(root: Path, network: str, bootstrap=(), *, limit=80, healthy_floor=HEALTHY_FLOOR):
    """Read metadata and only the requested prefix. No scoring/full-table scan."""
    try:
        with closing(_readonly(ranking_path(root,network))) as db:
            db.execute('BEGIN')  # metadata and endpoints from the same generation
            if db.execute('PRAGMA user_version').fetchone()[0] != FORMAT_VERSION:return None
            meta=db.execute('SELECT * FROM rank_meta WHERE singleton=1').fetchone()
            if not meta or meta['network']!=network or meta['policy']!=POLICY_VERSION:return None
            healthy,flaky=meta['healthy'],meta['flaky']
            if type(healthy) is not int or type(flaky) is not int or min(healthy,flaky)<0:return None
            count=healthy if healthy>=healthy_floor else healthy+flaky
            size=min(count,max(1,int(limit)))
            rows=db.execute('SELECT position,ip,port FROM rank_entries WHERE position<? ORDER BY position LIMIT ?',
                            (count,size)).fetchall()
            if len(rows)!=size or any(r['position']!=i for i,r in enumerate(rows)):return None
            # Detect truncated lists without loading the rest into the miner.
            last=db.execute('SELECT position FROM rank_entries ORDER BY position DESC LIMIT 1').fetchone()
            if (last[0]+1 if last else 0)!=healthy+flaky:return None
            peers=[endpoint(r['ip'],r['port']) for r in rows]
            for peer in peers:split_endpoint(peer)
        return select_ranked_peers(peers,bootstrap,healthy=healthy,flaky=flaky,
                                   limit=limit,healthy_floor=healthy_floor)
    except (sqlite3.Error,OSError,ValueError,TypeError,OverflowError):
        return None


class RankingSchedule:
    """At most one pending refresh per network, even while it is calculating."""
    def __init__(self, interval=RANK_INTERVAL_SECONDS, clock=time.monotonic):
        self.interval=interval
        self.clock=clock
        self.condition=threading.Condition()
        self.pending=set(NETWORKS)
        self.due={n:0.0 for n in NETWORKS}
        self.closed=False

    def request(self, network):
        if network not in NETWORKS:return
        with self.condition:
            self.pending.add(network)
            self.condition.notify()

    def next(self):
        with self.condition:
            while not self.closed:
                now=self.clock()
                self.pending.update(n for n,due in self.due.items() if due<=now)
                if self.pending:
                    network=min(self.pending,key=lambda n:self.due[n])
                    self.pending.remove(network)
                    self.due[network]=float('inf')
                    return network
                self.condition.wait(max(.01,min(self.due.values())-now))
        return None

    def finished(self,network):
        with self.condition:self.due[network]=self.clock()+self.interval

    def close(self):
        with self.condition:
            self.closed=True
            self.condition.notify_all()


def run_worker(root, stream=sys.stdin, *, interval=RANK_INTERVAL_SECONDS):
    schedule=RankingSchedule(interval)
    def commands():
        try:
            for line in stream:
                try:
                    command=json.loads(line)
                    if command.get('stop'):break
                    schedule.request(command.get('network'))
                except (ValueError,TypeError,AttributeError):continue
        finally:schedule.close()  # EOF also follows an unexpected parent exit
    reader=threading.Thread(target=commands,daemon=True)
    reader.start()
    while (network:=schedule.next()) is not None:
        try:
            if network_db_path(network,root).is_file():
                print(json.dumps(build_ranking(root,network)),flush=True)
        except Exception as exc:
            print(json.dumps(dict(network=network,error=str(exc)[:400])),flush=True)
        finally:schedule.finished(network)


class PeerRankingProcess:
    """App-owned child process. Requests never perform IPC on a miner/UI thread."""
    def __init__(self, root: Path, *, interval=RANK_INTERVAL_SECONDS):
        self.root=Path(root)
        self.interval=interval
        self.lock=threading.Lock()
        self.pending=set()
        self.wake=threading.Event()
        self.stop=threading.Event()
        self.thread=None
        self.process=None

    def request(self,network):
        if network not in NETWORKS:return
        with self.lock:self.pending.add(network)
        self.wake.set()

    def start(self):
        with self.lock:
            if self.stop.is_set() or (self.thread and self.thread.is_alive()):return
            self.thread=threading.Thread(target=self._supervise,name='CashMiner-ranking-control',daemon=True)
            self.thread.start()

    @staticmethod
    def _output(process):
        for line in process.stdout:
            try:
                status=json.loads(line)
                (LOG.warning if 'error' in status else LOG.info)('Ranking: %s',status)
            except ValueError:LOG.warning('Ranking: %s',line.strip()[:500])

    def _supervise(self):
        while not self.stop.is_set():
            process=None
            output=None
            try:
                env=os.environ.copy()
                env['PYTHONPATH']=str(Path(__file__).resolve().parents[2])
                env['PYTHONUTF8']='1'
                env['PYTHONDONTWRITEBYTECODE']='1'
                python_bin=Path(sys.executable)
                if os.name=='nt' and python_bin.name.lower()=='pythonw.exe':
                    # pythonw may have no stdio; use the same interpreter with
                    # pipes and CREATE_NO_WINDOW, as the existing miner does.
                    python_bin=python_bin.with_name('python.exe')
                    if not python_bin.is_file():raise OSError('Falta python.exe junto a pythonw.exe')
                process=subprocess.Popen([str(python_bin),'-m','cashminer.network.peer_rankings',
                    '--root',str(self.root),'--interval',str(self.interval)],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                    text=True,encoding='utf8',env=env,close_fds=True,
                    creationflags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|
                                   getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)))
                self.process=process
                output=threading.Thread(target=self._output,args=(process,),daemon=True)
                output.start()
                while not self.stop.is_set():
                    if process.poll() is not None:raise RuntimeError('El proceso de ranking finalizó')
                    with self.lock:
                        pending=self.pending.copy()
                        self.pending.clear()
                    for network in pending:process.stdin.write(json.dumps({'network':network})+'\n')
                    if pending:process.stdin.flush()
                    self.wake.wait(.5)
                    self.wake.clear()
            except (OSError,RuntimeError) as exc:
                LOG.warning('Ranking en segundo plano: %s; se conserva el selector tradicional',exc)
            finally:
                if process:
                    try:process.stdin.close()
                    except OSError:pass
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:process.wait(timeout=2)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
                    if output:output.join(timeout=2)
                    process.stdout.close()
                self.process=None
            if not self.stop.is_set():self.stop.wait(5)

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:self.thread.join(timeout=8)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--interval',type=float,default=RANK_INTERVAL_SECONDS)
    args=parser.parse_args()
    if args.interval<=0:parser.error('interval must be positive')
    run_worker(args.root,interval=args.interval)
