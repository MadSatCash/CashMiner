"""A local peer selection must never fabricate network activity."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.network.peer_store import PeerStore
from cashminer.network.runtime_peers import RuntimePeerRecorder,EVENT_PREFIX

ROOT=Path(os.environ.get('CASHMINER_TEST_BASE',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine

OLD='2025-01-01T00:00:00.000000+00:00'
NOW='2026-11-10T12:00:00.000000+00:00'

def packet(kind='peer_selected',**extra):
    value=dict(schema=1,network='testnet3',ip='1.2.3.4',port=18333,ts=NOW,kind=kind,
        sources=[dict(type='mining_selection',value='sqlite')])
    value.update(extra)
    return EVENT_PREFIX+json.dumps(value)


class SelectionActivity2143(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.st=PeerStore(self.root/'networks/testnet3.sqlite')
        self.st.add_peer('1.2.3.4',18333)
        self.st.record('1.2.3.4',18333,'handshake_ok',details={'services':33,'protocol_version':70016,'user_agent':'old-peer'})
        with self.st.connect() as c:
            c.execute('''UPDATE peers SET first_seen_at=?,last_seen_at=?,last_attempt_at=?,last_tcp_ok_at=?,
                last_handshake_ok_at=?,last_miner_event_at=?,runtime_event_count=7,last_status='old_status' ''',[OLD]*6)
        self.before=self.st.get('1.2.3.4',18333)
        self.rec=RuntimePeerRecorder(root=self.root,structured=True);self.addCleanup(self.rec.close)

    def observe(self,line):
        self.rec.observe('testnet3',line)
        self.assertTrue(self.rec.drain(5));self.assertEqual(self.rec.failures,0)

    def test_existing_peer_activity_row_remains_completely_unchanged(self):
        self.observe(packet())
        self.assertEqual(self.st.get('1.2.3.4',18333),self.before)
        with self.st.connect() as c:
            row=c.execute("SELECT event_type,timestamp FROM peer_events ORDER BY event_id DESC LIMIT 1").fetchone()
            source=c.execute("SELECT last_seen_at FROM peer_sources WHERE source_type='mining_selection'").fetchone()
            self.assertEqual(c.execute("SELECT COUNT(*) FROM peer_sources WHERE source_type='runtime'").fetchone()[0],0)
        self.assertEqual(tuple(row),('peer_selected',NOW));self.assertEqual(source[0],NOW)

    def test_new_selected_peer_has_unknown_activity(self):
        self.observe(packet(ip='8.8.8.8'))
        row=self.st.get('8.8.8.8',18333)
        self.assertIsNotNone(row)
        for key,value in row.items():
            if key.endswith('_at') or key=='last_status':self.assertIsNone(value,key)
            if key.endswith('_count'):self.assertEqual(value,0,key)
        self.observe(packet(kind='tcp_ok',ip='8.8.8.8',sources=[]))
        after=self.st.get('8.8.8.8',18333)
        self.assertEqual(after['first_seen_at'],NOW)
        self.assertEqual(after['last_seen_at'],NOW)
        self.assertEqual(after['tcp_ok_count'],1)

    def test_repeated_selection_only_updates_selection_history(self):
        for _ in range(3):self.observe(packet())
        self.assertEqual(self.st.get('1.2.3.4',18333),self.before)
        with self.st.connect() as c:
            self.assertEqual(c.execute("SELECT seen_count FROM peer_sources WHERE source_type='mining_selection'").fetchone()[0],3)

    def test_discovery_fills_unknown_first_seen_after_selection(self):
        self.observe(packet(ip='8.8.8.8'))
        discovered='2026-11-11T12:00:00.000000+00:00'
        self.st.add_peer('8.8.8.8',18333,source_type='peer',
                         source_value='1.2.3.4:18333',seen_at=discovered)
        row=self.st.get('8.8.8.8',18333)
        self.assertEqual(row['first_seen_at'],discovered)
        self.assertEqual(row['last_seen_at'],discovered)
        self.assertIsNone(row['last_status'])
        for key,value in row.items():
            if key.endswith('_count'):self.assertEqual(value,0,key)

    def test_discovery_preserves_existing_first_seen_and_latest_last_seen(self):
        self.st.add_peer('1.2.3.4',18333,source_type='seed',
                         source_value='seed.example',seen_at=NOW)
        self.st.add_peer('1.2.3.4',18333,seen_at=OLD)
        row=self.st.get('1.2.3.4',18333)
        self.assertEqual(row['first_seen_at'],OLD)
        self.assertEqual(row['last_seen_at'],NOW)
        for key,value in self.before.items():
            if key not in ('first_seen_at','last_seen_at'):self.assertEqual(row[key],value,key)

    def test_old_2142_selection_packet_is_also_safe(self):
        self.observe(packet(kind='peer_seen'))
        self.assertEqual(self.st.get('1.2.3.4',18333),self.before)

    def test_real_connection_after_selection_does_update_activity(self):
        self.observe(packet())
        self.observe(packet(kind='tcp_ok',sources=[]))
        after=self.st.get('1.2.3.4',18333)
        self.assertEqual(after['last_seen_at'],NOW);self.assertEqual(after['last_tcp_ok_at'],NOW)
        self.assertEqual(after['tcp_ok_count'],self.before['tcp_ok_count']+1)
        self.assertEqual(after['runtime_event_count'],self.before['runtime_event_count']+1)

    def test_actual_discovery_keeps_its_original_observation_semantics(self):
        self.observe(packet(kind='peer_seen',sources=[dict(type='seed',value='seed.example')]))
        self.assertEqual(self.st.get('1.2.3.4',18333)['last_seen_at'],NOW)

    def test_raw_store_compatibility_does_not_depend_on_parser(self):
        self.st.record('1.2.3.4',18333,'peer_seen',details={'sources':[{'type':'mining_selection','value':'combined'}]})
        self.assertEqual(self.st.get('1.2.3.4',18333),self.before)

    def test_engine_startup_records_selection_without_observing_peer(self):
        output=io.StringIO()
        with patch.dict(os.environ,{'CASHMINER2_PEER_EVENTS':'1','CASHMINER2_PEER_SOURCE':'sqlite'}), \
             patch.object(engine,'NETWORK','testnet3'),patch.object(engine,'MINER_MODE','p2p-tip'), \
             patch.object(engine,'BROADCAST_PEERS',['1.2.3.4:18333']),contextlib.redirect_stdout(output):
            engine.start_peer_db_writer_if_enabled()
            try:engine.PEER_EVENT_QUEUE.join()
            finally:engine.stop_peer_db_writer()
        lines=[line for line in output.getvalue().splitlines() if EVENT_PREFIX in line]
        self.assertEqual(len(lines),1)
        self.observe(lines[0])
        self.assertEqual(self.st.get('1.2.3.4',18333),self.before)


if __name__=='__main__':unittest.main()
