"""Persistent ranking: policy equivalence, real IPC, crashes and source isolation."""
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from cashminer.app import server
from cashminer.mining import peer_sources
from cashminer.network import peer_rankings as ranks, policy
from cashminer.network.endpoints import endpoint
from cashminer.network.networks import NETWORKS
from cashminer.network.peer_store import PeerStore
from cashminer.network.p2p import Probe
from cashminer.network.scoring import operational_score
from cashminer.wallet.legacy_hd import address_from_secret

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,10,12,tzinfo=timezone.utc)


def rows(count):
    rng=random.Random(215)
    result=[]
    for i in range(count):
        ok=(NOW-timedelta(days=rng.randrange(200))).isoformat()
        result.append(dict(ip=f'10.{i//65536}.{i//256%256}.{i%256}',port=8333,
            handshake_ok_count=rng.randrange(12),last_handshake_ok_at=ok,
            last_attempt_at=ok if i%3 else (NOW+timedelta(seconds=1)).isoformat(),
            tcp_fail_count=rng.randrange(4),handshake_fail_count=rng.randrange(3),
            broadcast_getdata_count=rng.randrange(10),
            last_chain_incompatible_at=NOW.isoformat() if i%7==0 else None,
            last_chain_compatible_at=None))
    return result


def historical_selection(data, bootstrap, *, limit=80, floor=8):
    # Independent reproduction of the old selector, reusing the score function.
    candidates=[r for r in data if int(r.get('handshake_ok_count') or 0)>0]
    candidates.sort(key=lambda r:(bool(policy.chain_incompatible_recently(r)),
        -operational_score(r,NOW),str(r.get('last_handshake_ok_at') or ''),r['ip'],r['port']))
    healthy=[r for r in candidates if policy.is_healthy(r) and not policy.chain_incompatible_recently(r)]
    flaky=[r for r in candidates if r not in healthy]
    selected=healthy if len(healthy)>=floor else healthy+flaky
    out=[]
    for candidate in [endpoint(r['ip'],r['port']) for r in selected]+list(bootstrap):
        if candidate not in out:out.append(candidate)
        if len(out)>=limit:break
    return dict(peers=tuple(out),healthy=len(healthy),flaky=len(flaky),
        bootstrap=len(bootstrap),used_fallback=len(healthy)<floor)


class PeerRankings215(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)

    def populate(self,data,network='mainnet'):
        st=PeerStore(self.root/'networks'/(network+'.sqlite'))
        if data:
            keys=list(data[0])
            with st.connect() as db:
                db.executemany('INSERT OR REPLACE INTO peers('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',
                               ([r.get(k) for k in keys] for r in data))
        return st

    def build(self,data=None,network='mainnet'):
        if data is not None:self.populate(data,network)
        return ranks.build_ranking(self.root,network,now=NOW)

    def decision(self,source='sqlite',network='mainnet',store=None,request=None):
        return peer_sources.initial_mining_peers(NETWORKS[network],source,
            store or PeerStore(self.root/'networks'/(network+'.sqlite')),
            ranking_root=self.root,request_ranking=request)

    def test_policy_refactoring_matches_historical_selection(self):
        for count in (0,3,9,100):
            data=rows(count)
            for limit in (0,1,7,80,200):
                for floor in (0,8,200):
                    bootstrap=['1.2.3.4:8333','[::1]:8333','1.2.3.4:8333']
                    self.assertEqual(policy.choose_mining_peers(data,bootstrap,limit=limit,healthy_floor=floor,now=NOW),
                        historical_selection(data,bootstrap,limit=limit,floor=floor))

    def test_saved_ranking_equals_live_selection_at_same_instant(self):
        data=rows(400)
        self.build(data)
        for limit in (1,8,80,1000):
            for floor in (0,8,1000):
                bootstrap=['10.0.0.1:8333','[::1]:8333']
                self.assertEqual(ranks.read_ranking(self.root,'mainnet',bootstrap,limit=limit,healthy_floor=floor),
                    policy.choose_mining_peers(data,bootstrap,limit=limit,healthy_floor=floor,now=NOW))

    def test_all_15000_eligible_refs_saved_not_only_first_80_or_10000(self):
        data=rows(15000)
        for row in data:row['handshake_ok_count']=max(1,row['handshake_ok_count'])
        result=self.build(data)
        self.assertEqual(result['eligible'],15000)
        path=ranks.ranking_path(self.root,'mainnet')
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rank_entries').fetchone()[0],15000)
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(rank_entries)')],['position','ip','port'])
        self.assertEqual(ranks.read_ranking(self.root,'mainnet',limit=20000,healthy_floor=20000),
            policy.choose_mining_peers(data,[],limit=20000,healthy_floor=20000,now=NOW))

    def test_networks_are_independent_and_wrong_metadata_falls_back(self):
        for i,net in enumerate(NETWORKS):
            data=rows(1);data[0].update(ip=f'1.2.3.{i+1}',handshake_ok_count=2)
            self.build(data,net)
            self.assertEqual(ranks.read_ranking(self.root,net)['peers'],(f'1.2.3.{i+1}:8333',))
        with closing(sqlite3.connect(ranks.ranking_path(self.root,'mainnet'))) as db, db:
            db.execute("UPDATE rank_meta SET network='chipnet'")
        self.assertIsNone(ranks.read_ranking(self.root,'mainnet'))

    def test_build_and_read_never_modify_original_tables(self):
        st=self.populate(rows(40))
        with st.connect() as db:before='\n'.join(db.iterdump())
        for _ in range(2):
            self.build();ranks.read_ranking(self.root,'mainnet')
        with st.connect() as db:self.assertEqual('\n'.join(db.iterdump()),before)

    def test_empty_ranking_retains_bootstrap_and_source_rules(self):
        self.build([])
        result=ranks.read_ranking(self.root,'mainnet',['1.2.3.4:8333'])
        self.assertEqual(result['peers'],('1.2.3.4:8333',))
        with self.assertRaisesRegex(ValueError,'No hay candidatos'):self.decision()

    def test_dns_exclusive_never_reads_ranking_or_sqlite(self):
        st=Mock()
        with patch.object(peer_sources,'read_ranking') as read,patch.object(peer_sources,'discover_dns',return_value=[('1.2.3.4',8333,'seed')]):
            result=self.decision('dns',store=st)
        self.assertEqual(result['peers'],('1.2.3.4:8333',))
        read.assert_not_called();st.peers.assert_not_called()

    def test_cached_sources_never_load_or_score_original_peers(self):
        data=rows(3)
        for row in data:row['handshake_ok_count']=1
        self.build(data)
        st=Mock()
        for source in ('sqlite','combined','legacy'):
            with patch.object(peer_sources,'choose_mining_peers',side_effect=AssertionError('live scoring')), \
                 patch.object(peer_sources,'discover_dns',return_value=[('1.2.3.4',8333,'seed')]) as dns:
                result=self.decision(source,store=st)
            self.assertTrue(result['peers']);st.peers.assert_not_called()
            self.assertEqual(dns.call_count,int(source=='combined'))

    def test_combined_deduplicates_and_keeps_historical_80_cap(self):
        data=rows(100)
        for row in data:row.update(handshake_ok_count=1,last_attempt_at=NOW.isoformat(),last_handshake_ok_at=NOW.isoformat())
        self.build(data)
        dns=[('10.0.0.1',8333,'seed'),('1.2.3.4',8333,'seed')]
        with patch.object(peer_sources,'discover_dns',return_value=dns):result=self.decision('combined')
        expected=policy.choose_mining_peers(data,[endpoint(ip,port) for ip,port,_ in dns],now=NOW)
        self.assertEqual(result['peers'],expected['peers']);self.assertEqual(len(result['peers']),80)

    def test_missing_ranking_uses_live_selector_and_requests_rebuild(self):
        data=rows(10);self.populate(data);request=Mock()
        result=self.decision(request=request)
        self.assertTrue(result['peers']);request.assert_called_once_with('mainnet')

    def test_empty_saved_ranking_does_not_hide_new_live_candidates(self):
        self.build([])
        st=PeerStore(self.root/'networks/mainnet.sqlite')
        st.record('1.2.3.4',8333,'handshake_ok')
        request=Mock()
        self.assertEqual(self.decision(request=request)['peers'],('1.2.3.4:8333',))
        request.assert_called_once_with('mainnet')

    def test_history_only_database_is_read_without_initializing_peers(self):
        path=self.root/'networks/mainnet.sqlite';path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db, db:db.execute('CREATE TABLE history(dummy)')
        self.build()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('history',)])

    def test_corrupt_ranking_falls_back_and_can_be_rebuilt(self):
        data=rows(10);self.populate(data)
        path=ranks.ranking_path(self.root,'mainnet');path.parent.mkdir()
        path.write_bytes(b'not a database')
        self.assertTrue(self.decision()['peers'])
        self.build()
        self.assertIsNotNone(ranks.read_ranking(self.root,'mainnet'))

    def test_incompatible_format_or_policy_falls_back_and_rebuilds(self):
        self.build(rows(10))
        path=ranks.ranking_path(self.root,'mainnet')
        for sql in ('PRAGMA user_version=999',"UPDATE rank_meta SET policy='other'"):
            with closing(sqlite3.connect(path)) as db, db:db.execute(sql)
            self.assertIsNone(ranks.read_ranking(self.root,'mainnet'))
            self.assertTrue(self.decision()['peers'])
            self.build();self.assertIsNotNone(ranks.read_ranking(self.root,'mainnet'))

    def test_truncated_ranking_falls_back(self):
        self.build(rows(100))
        with closing(sqlite3.connect(ranks.ranking_path(self.root,'mainnet'))) as db, db:
            db.execute('DELETE FROM rank_entries WHERE position=0')
        self.assertIsNone(ranks.read_ranking(self.root,'mainnet'))
        self.assertTrue(self.decision()['peers'])

    def test_old_calculation_date_does_not_expire(self):
        self.populate(rows(10))
        ranks.build_ranking(self.root,'mainnet',now=datetime(2000,1,1,tzinfo=timezone.utc))
        with patch.object(peer_sources,'choose_mining_peers',side_effect=AssertionError('no expiry')):
            self.assertTrue(self.decision()['peers'])

    def test_observations_change_only_next_calculation(self):
        data=rows(2)
        for row in data:row.update(handshake_ok_count=2,last_attempt_at=NOW.isoformat(),last_handshake_ok_at=NOW.isoformat(),last_chain_incompatible_at=None)
        st=self.populate(data);self.build()
        before=ranks.read_ranking(self.root,'mainnet')
        first=before['peers'][0].split(':')[0]
        with st.connect() as db:db.execute('UPDATE peers SET handshake_ok_count=0 WHERE ip=?',(first,))
        self.assertEqual(ranks.read_ranking(self.root,'mainnet'),before)
        self.build();self.assertNotIn(first+':8333',ranks.read_ranking(self.root,'mainnet')['peers'])

    def test_age_changes_order_on_next_calculation(self):
        data=[dict(ip='1.1.1.1',port=8333,handshake_ok_count=3,last_handshake_ok_at='2010-01-01T00:00:00+00:00'),
              dict(ip='2.2.2.2',port=8333,handshake_ok_count=1,last_handshake_ok_at=NOW.isoformat())]
        self.build(data)
        self.assertEqual(ranks.read_ranking(self.root,'mainnet')['peers'][0],'2.2.2.2:8333')
        ranks.build_ranking(self.root,'mainnet',now=NOW+timedelta(days=90))
        self.assertEqual(ranks.read_ranking(self.root,'mainnet')['peers'][0],'1.1.1.1:8333')

    def test_busy_update_preserves_previous_committed_ranking(self):
        self.build(rows(10));before=ranks.read_ranking(self.root,'mainnet')
        with closing(sqlite3.connect(ranks.ranking_path(self.root,'mainnet'))) as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):self.build()
            self.assertEqual(ranks.read_ranking(self.root,'mainnet'),before)
            db.rollback()

    def test_simultaneous_readers_only_see_complete_generations(self):
        self.build(rows(60));stop=threading.Event();errors=[]
        old=ranks.read_ranking(self.root,'mainnet')['peers']
        healthy,flaky=policy.rank_mining_candidates(rows(3),now=NOW)
        expected=policy.choose_mining_peers(rows(3),[],now=NOW)['peers']
        def reader():
            while not stop.is_set():
                value=ranks.read_ranking(self.root,'mainnet')
                if value is None or value['peers'] not in (old,expected):errors.append(value)
        thread=threading.Thread(target=reader);thread.start()
        try:
            for _ in range(4):
                ranks._publish(ranks.ranking_path(self.root,'mainnet'),'mainnet',healthy,flaky,NOW.isoformat())
                self.build()
        finally:stop.set();thread.join(3)
        self.assertFalse(errors)

    def test_killing_writer_before_commit_preserves_previous_ranking(self):
        self.build(rows(60));before=ranks.read_ranking(self.root,'mainnet')
        ready=self.root/'writer-ready'
        script='''import sqlite3,time,sys
from pathlib import Path
db=sqlite3.connect(sys.argv[1]);db.execute('BEGIN IMMEDIATE')
db.execute('DELETE FROM rank_entries');db.execute('DELETE FROM rank_meta')
Path(sys.argv[2]).touch()
time.sleep(30)
'''
        child=subprocess.Popen([sys.executable,'-c',script,str(ranks.ranking_path(self.root,'mainnet')),str(ready)],
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            end=time.monotonic()+5
            while not ready.exists() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(ready.exists())
            self.assertEqual(ranks.read_ranking(self.root,'mainnet'),before)
        finally:child.kill();child.wait(timeout=5)
        self.assertEqual(ranks.read_ranking(self.root,'mainnet'),before)
        self.build()

    def test_repeated_updates_do_not_accumulate_history(self):
        self.build(rows(40))
        for _ in range(4):self.build()
        with closing(sqlite3.connect(ranks.ranking_path(self.root,'mainnet'))) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rank_meta').fetchone()[0],1)
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM rank_entries').fetchone()[0],40)
        self.assertEqual(list((self.root/'rankings').glob('*.sqlite')),[ranks.ranking_path(self.root,'mainnet')])

    def test_periodic_process_updates_without_miner_restart_and_closes(self):
        st=self.populate(rows(10))
        worker=ranks.PeerRankingProcess(self.root,interval=.2)
        worker.start();self.addCleanup(worker.close)
        def wait_for(predicate):
            end=time.monotonic()+8
            while time.monotonic()<end:
                value=ranks.read_ranking(self.root,'mainnet')
                if value and predicate(value):return value
                time.sleep(.02)
            self.fail('worker did not publish')
        before=wait_for(lambda d:bool(d['peers']))
        first=before['peers'][0].split(':')[0]
        with st.connect() as db:db.execute('UPDATE peers SET handshake_ok_count=0 WHERE ip=?',(first,))
        wait_for(lambda d:first+':8333' not in d['peers'])
        process=worker.process
        self.assertNotEqual(process.pid,os.getpid())
        worker.close();self.assertIsNotNone(process.poll())
        self.assertFalse(worker.thread.is_alive())

    def test_failed_child_start_does_not_block_live_selection(self):
        self.populate(rows(10))
        worker=ranks.PeerRankingProcess(self.root)
        with patch.object(ranks.subprocess,'Popen',side_effect=OSError('unavailable')):
            worker.start()
            try:self.assertTrue(self.decision(request=worker.request)['peers'])
            finally:worker.close()

    def test_miner_start_uses_saved_candidates_without_live_scoring(self):
        self.build(rows(100))
        expected=ranks.read_ranking(self.root,'mainnet')['peers']
        with patch.dict(os.environ,{'CASHMINER_DATA_DIR':str(self.root)}), \
             patch.object(server,'PREF_FILE',self.root/'settings.json'):
            service=server.CashMinerService()
            try:
                service.configure_mining_connection({'network':'mainnet','mode':'p2p-tip','peer_source':'sqlite'})
                slot=service.sessions['mainnet']
                with patch.object(slot.mining,'start',return_value=[]) as start, \
                     patch.object(PeerStore,'peers',side_effect=AssertionError('full read')), \
                     patch.object(peer_sources,'choose_mining_peers',side_effect=AssertionError('full ranking')):
                    service.start_miner({'network':'mainnet','target_mode':'address',
                                         'address':address_from_secret(1,'mainnet')})
                self.assertEqual(start.call_args.args[0].peers,expected)
                self.assertEqual(start.call_args.args[0].peer_source,'sqlite')
            finally:service.stop_all()

    def test_source_writes_continue_during_background_calculation(self):
        st=self.populate(rows(50));entered=threading.Event();resume=threading.Event()
        original=ranks.rank_mining_candidates;errors=[]
        def slow(data,**kwargs):
            entered.set()
            if not resume.wait(5):raise AssertionError('test timeout')
            return original(data,**kwargs)
        def build():
            try:self.build()
            except Exception as exc:errors.append(exc)
        with patch.object(ranks,'rank_mining_candidates',side_effect=slow):
            thread=threading.Thread(target=build);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                st.record('1.2.3.4',8333,'handshake_ok')
                self.assertEqual(st.get('1.2.3.4',8333)['handshake_ok_count'],1)
            finally:resume.set();thread.join(5)
        self.assertFalse(errors)
        self.assertNotIn('1.2.3.4:8333',ranks.read_ranking(self.root,'mainnet')['peers'])
        self.build()
        self.assertIn('1.2.3.4:8333',ranks.read_ranking(self.root,'mainnet',healthy_floor=1000)['peers'])

    def test_child_exits_when_parent_command_pipe_closes(self):
        worker=ranks.PeerRankingProcess(self.root,interval=30)
        worker.start()
        try:
            end=time.monotonic()+5
            while worker.process is None and time.monotonic()<end:time.sleep(.01)
            self.assertIsNotNone(worker.process)
            process=worker.process
            # Simulate losing the parent, without a stop message.
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5),0)
        finally:worker.close()

    @unittest.skipUnless(os.name=='nt','Windows pythonw launcher')
    def test_pythonw_parent_uses_hidden_python_with_working_ipc(self):
        self.populate(rows(10))
        pythonw=Path(sys.executable).with_name('pythonw.exe')
        real_popen=subprocess.Popen
        worker=ranks.PeerRankingProcess(self.root,interval=30)
        with patch.object(ranks.sys,'executable',str(pythonw)), \
             patch.object(ranks.subprocess,'Popen',wraps=real_popen) as spawn:
            worker.start()
            try:
                end=time.monotonic()+8
                while ranks.read_ranking(self.root,'mainnet') is None and time.monotonic()<end:time.sleep(.02)
                self.assertIsNotNone(ranks.read_ranking(self.root,'mainnet'))
                self.assertEqual(Path(spawn.call_args.args[0][0]).name.lower(),'python.exe')
                self.assertTrue(spawn.call_args.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW)
            finally:worker.close()

    def test_schedule_coalesces_requests_and_preserves_one_during_build(self):
        clock=[0.0];schedule=ranks.RankingSchedule(interval=300,clock=lambda:clock[0])
        schedule.pending.clear();schedule.due={n:1000 for n in NETWORKS}
        for _ in range(100):schedule.request('mainnet')
        self.assertEqual(schedule.pending,{'mainnet'})
        self.assertEqual(schedule.next(),'mainnet')
        for _ in range(100):schedule.request('mainnet')
        schedule.finished('mainnet')
        self.assertEqual(schedule.next(),'mainnet')
        schedule.finished('mainnet');self.assertFalse(schedule.pending)
        clock[0]=301
        self.assertEqual(schedule.next(),'mainnet')
        schedule.close();self.assertIsNone(schedule.next())

    def test_explorer_completion_requests_refresh_without_changing_probes(self):
        with patch.dict(os.environ,{'CASHMINER_DATA_DIR':str(self.root)}), \
             patch.object(server,'PREF_FILE',self.root/'settings.json'):
            service=server.CashMinerService()
            try:
                self.populate([dict(ip='1.2.3.4',port=8333)])
                with patch.object(service.peer_rankings,'request') as request, \
                     patch.object(server,'discover_dns',return_value=[]), \
                     patch.object(server,'probe_peer',return_value=Probe('1.2.3.4',8333,connected=True,handshake=True,addr_received=True)) as probe:
                    service._explore_cycle_batch('mainnet')
                request.assert_called_once_with('mainnet');probe.assert_called_once()
            finally:service.stop_all()


if __name__=='__main__':unittest.main()
