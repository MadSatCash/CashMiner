"""A9: automated full cycles, bounded work queue, pause/resume and independent toggles.

All probes and DNS discovery are isolated fakes; no public node is contacted.
"""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.network.peer_store import PeerStore
from cashminer.network.p2p import Probe


class ExplorerScheduler214a9(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for p in [patch.dict(os.environ,{'CASHMINER_DATA_DIR':str(self.root)}),
                  patch.object(app_server,'PREF_FILE',self.root/'settings.json'),
                  patch.object(app_server,'network_db_path',lambda n:self.root/'networks'/f'{n}.sqlite')]:
            p.start();self.addCleanup(p.stop)
        self.service=app_server.CashMinerService()
        self.addCleanup(self.service.stop_all)

    def store(self,n='mainnet'):
        return PeerStore(self.root/'networks'/f'{n}.sqlite')

    def test_initial_preferences_regtest_and_all_master_controls(self):
        a=self.service.prefs
        self.assertTrue(a['explorer_auto_master'])
        self.assertTrue(a['explorer_continuous_master'])
        self.assertFalse(a['explorer_auto_by_network']['regtest'])
        self.assertTrue(all(a['explorer_auto_by_network'][net] for net in app_server.NETWORKS if net!='regtest'))
        self.assertFalse(any(self.service.explorer_manual.values()))
        self.service.set_explorer_mode('automatic',False,'mainnet')
        self.service.set_explorer_mode('automatic',False)
        self.service.set_explorer_mode('continuous',False)
        self.service.set_explorer_mode('automatic',True)  # doesn't change Mainnet or Regtest
        read=app_server._prefs_read()
        self.assertFalse(read['explorer_auto_by_network']['mainnet'])
        self.assertFalse(read['explorer_auto_by_network']['regtest'])
        self.assertTrue(read['explorer_auto_by_network']['testnet3'])
        self.assertTrue(read['explorer_auto_master'])
        self.assertFalse(read['explorer_continuous_master'])
        with self.assertRaises(ValueError):self.service.set_explorer_mode('automatic',1,'mainnet')
        with self.assertRaises(ValueError):self.service.set_explorer_mode('continuous',True,'xyz')

    def test_cycle_snapshot_resume_after_crash_and_one_completion_timestamp(self):
        st=self.store()
        for ip in ('1.1.1.1','2.2.2.2','3.3.3.3'):
            st.add_peer(ip,8333)
        s=self.service
        s.prefs['miner_settings']['mainnet']['peers_per_round']=2
        visited=[]
        def fake(net,ip,port,**kwargs):
            visited.append(ip)
            # Discovery during the first batch must not extend its frozen queue.
            return Probe(ip,port,connected=True,handshake=True,addr_received=True,
                candidates=[('4.4.4.4',8333)] if ip=='1.1.1.1' else [])
        with patch.object(app_server,'discover_dns',return_value=[]),patch.object(app_server,'probe_peer',side_effect=fake):
            s._explore_cycle_batch('mainnet')
            midway=st.explorer_cycle_status()
            self.assertEqual((midway['total'],midway['processed'],midway['active']),(3,2,True))
            self.assertIsNone(midway['last_completed_at'])
            # A new service instance must continue the unfinished cycle.
            s2=app_server.CashMinerService()
            try:
                s2._explore_cycle_batch('mainnet')
            finally:
                s2.stop_all()
        complete=st.explorer_cycle_status()
        self.assertEqual(complete['last_completed_at'] is not None,True)
        self.assertFalse(complete['active'])
        self.assertEqual(complete['total'],3)
        self.assertEqual(sorted(visited),['1.1.1.1','2.2.2.2','3.3.3.3'])
        self.assertEqual(st.get('4.4.4.4',8333)['ip'],'4.4.4.4')
        with st.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM explorer_cycle_queue').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM explorer_cycle_state').fetchone()[0],1)
        # New cycle uses newly discovered peers, but never accumulates prior cycle rows.
        with patch.object(app_server,'discover_dns',return_value=[]),patch.object(app_server,'probe_peer',side_effect=fake):
            s._explore_cycle_batch('mainnet')
        self.assertEqual(st.explorer_cycle_status()['total'],4)
        self.assertEqual(st.explorer_cycle_status()['processed'],2)

    def test_pending_queue_can_only_finish_if_all_attempts_are_durable(self):
        st=self.store()
        st.add_peer('1.2.3.4',8333)
        st.explorer_begin_cycle()
        with self.assertRaisesRegex(ValueError,'incompleto'):
            st.explorer_complete_cycle()
        st.explorer_mark_attempted('1.2.3.4',8333)
        when=st.explorer_complete_cycle()
        self.assertEqual(st.explorer_cycle_status()['last_completed_at'],when)
        self.assertEqual(st.explorer_pending_batch(25),[])

    def test_schedule_one_network_at_a_time_and_no_regtest_by_default(self):
        self.store('mainnet').add_peer('1.1.1.1',8333)
        self.store('testnet3').add_peer('2.2.2.2',18333)
        seen=[];lock=threading.Lock();active=[]
        def fake(net,ip,port,**kwargs):
            with lock:
                active.append(net.name)
                self.assertEqual(len(set(active)),1)
                seen.append(net.name)
            time.sleep(.03)
            with lock:active.remove(net.name)
            return Probe(ip,port,connected=True,handshake=True,addr_received=False,candidates=[])
        with patch.object(app_server,'discover_dns',return_value=[]),patch.object(app_server,'probe_peer',side_effect=fake):
            self.service.start_explorer_automation()
            deadline=time.monotonic()+9
            while time.monotonic()<deadline:
                if self.store('mainnet').explorer_cycle_status()['last_completed_at'] and self.store('testnet3').explorer_cycle_status()['last_completed_at']:
                    break
                time.sleep(.05)
        self.assertIn('mainnet',seen)
        self.assertIn('testnet3',seen)
        self.assertEqual(self.store('regtest').explorer_cycle_status()['last_completed_at'],None)
        self.assertFalse(self.service.explorer_manual['regtest'])

    def test_sync_grace_has_absolute_deadline_not_infinite_wait(self):
        self.store('mainnet').add_peer('1.1.1.1',8333)
        for net in list(app_server.NETWORKS):
            if net!='mainnet':self.service.set_explorer_mode('automatic',False,net)
        called=threading.Event()
        def fake(net,ip,port,**kwargs):
            called.set()
            return Probe(ip,port,connected=True,handshake=True,addr_received=False,candidates=[])
        with patch.object(app_server,'PEER_EXPLORER_AUTO_SYNC_GRACE_SECONDS',0.5), \
             patch.object(self.service.wallet_sync,'syncing_for_explorer',return_value=True), \
             patch.object(app_server,'discover_dns',return_value=[]), \
             patch.object(app_server,'probe_peer',side_effect=fake):
            self.service.start_explorer_automation()
            self.assertFalse(called.wait(.15))
            self.assertTrue(called.wait(3))  # even though syncing_for_explorer stays True

    def test_global_continuous_suspends_individual_without_changing_choice(self):
        self.service.set_explorer_mode('continuous',False)
        self.service.start_exploring('chipnet')
        self.assertTrue(self.service.explorer_manual['chipnet'])
        self.assertFalse(self.service._explorer_enabled('chipnet')[0])
        self.service.set_explorer_mode('continuous',True)
        self.assertTrue(self.service._explorer_enabled('chipnet')[0])
        self.service.stop_exploring('chipnet')
        self.assertFalse(self.service.explorer_manual['chipnet'])


if __name__=='__main__':unittest.main()
