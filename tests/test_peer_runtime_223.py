"""Regresión P2P v2.2.3: no requiere red, DLL ni GPU."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.network.policy import choose_mining_peers, is_healthy, chain_incompatible_recently
from cashminer.network.runtime_peers import parse_runtime_line, RuntimePeerRecorder
from cashminer.network.peer_store import PeerStore
from cashminer.config import network_db_path
from cashminer.app import server as app_server


class PeerSelection223(unittest.TestCase):
    def peer(self, host, *, ok='2026-11-06T20:00:00+00:00', attempt=None, count=1,
             incompatible=None, compatible=None):
        return dict(ip=host,port=48335,handshake_ok_count=count,last_handshake_ok_at=ok,
                    last_attempt_at=attempt or ok, last_chain_incompatible_at=incompatible,
                    last_chain_compatible_at=compatible,
                    handshake_fail_count=0,tcp_fail_count=0,broadcast_getdata_count=0)

    def test_healthy_and_flaky_have_distinct_meaning(self):
        healthy=self.peer('1.1.1.1')
        flaky=self.peer('2.2.2.2',attempt='2026-11-06T20:01:00+00:00')
        self.assertTrue(is_healthy(healthy)); self.assertFalse(is_healthy(flaky))
        d=choose_mining_peers([flaky,healthy],['3.3.3.3:48335'],healthy_floor=8)
        self.assertEqual(d['peers'][0],'1.1.1.1:48335')
        self.assertEqual(set(d['peers']),{'1.1.1.1:48335','2.2.2.2:48335','3.3.3.3:48335'})
        self.assertTrue(d['used_fallback'])

    def test_abundant_healthy_excludes_failed(self):
        peers=[self.peer(f'10.0.0.{i}') for i in range(1,10)]
        fail=self.peer('10.0.0.99',attempt='2026-11-06T20:01:00+00:00')
        d=choose_mining_peers(peers+[fail],['3.3.3.3:48335'])
        self.assertEqual(d['healthy'],9)
        self.assertEqual(d['flaky'],1)
        self.assertNotIn('10.0.0.99:48335',d['peers'])
        self.assertIn('3.3.3.3:48335',d['peers'])

    def test_incompatibility_is_not_permanent_but_never_consensus(self):
        p=self.peer('1.2.3.4',incompatible='2026-11-06T22:01:00+00:00',
                    compatible='2026-11-06T22:00:00+00:00')
        self.assertTrue(chain_incompatible_recently(p))
        p['last_chain_compatible_at']='2026-11-06T22:02:00+00:00'
        self.assertFalse(chain_incompatible_recently(p))

    def test_no_invalid_handshake_synthesized_from_bootstrap(self):
        p=self.peer('1.2.3.4',count=0,ok=None)
        d=choose_mining_peers([p],['1.2.3.4:48335'])
        self.assertEqual(d['peers'],('1.2.3.4:48335',))


class Runtime223(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_realistic_runtime_lines(self):
        tip='[2026-11-06 21:17:00] [tempnet:p2p-observation] peer=15.204.253.47:48335 candidate_height=359495 candidate_hash='+'a'*64+' candidate_prev_hash='+'b'*64
        events=parse_runtime_line(tip)
        self.assertEqual([e.kind for e in events],['connect_attempt','tcp_ok','handshake_ok','headers_observed','chain_compatible'])
        fail='[2026-11-06 21:17:45] [tempnet:p2p] peer descartado 15.204.228.134:48333: [WinError 10061] No se puede establecer una conexión'
        self.assertEqual([e.kind for e in parse_runtime_line(fail)],['connect_attempt','tcp_fail'])
        incompatible='[tempnet:p2p] peer descartado 135.148.26.244:49333: primer bloque no corresponde a tempnet FABLOUS 2026'
        self.assertEqual(parse_runtime_line(incompatible)[-1].kind,'chain_incompatible')
        getdata='[2026] [broadcast:OK] 15.204.253.47:48335 -> peer pidió el bloque y fue enviado: '+'a'*64
        self.assertEqual([e.kind for e in parse_runtime_line(getdata)],['broadcast_attempt','broadcast_getdata'])
        no_getdata='[broadcast:OK] 134.199.159.4:59333 -> peer aceptó/anunció headers pero no pidió block: '+'a'*64
        self.assertEqual(parse_runtime_line(no_getdata)[-1].kind,'broadcast_headers_ok')
        self.assertEqual(parse_runtime_line('[broadcast:FAIL] 134.199.159.4:59333 -> timeout esperando getdata/reject')[-1].kind,'broadcast_timeout')
        response='[tempnet:peer-observation] block_hash='+'a'*64+' height=359495 peer=15.204.253.47:48335 utc_start=x status=response stage=completed headers_count=2 more_headers_possible=False'
        self.assertEqual(parse_runtime_line(response)[0].kind,'headers_response')
        self.assertFalse(parse_runtime_line('[*] engine=CUDA0 h=350000 rate_total=0 H/s'))

    def test_event_pipeline_does_not_touch_miner_and_is_persistent(self):
        rec=RuntimePeerRecorder(root=self.root)
        rec.observe('tempnet_fablous_2026','[tempnet:p2p-observation] peer=1.2.3.4:48335 candidate_height=359495 candidate_hash='+'a'*64)
        rec.observe('tempnet_fablous_2026','[broadcast:FAIL] 1.2.3.4:48335 -> timeout esperando getdata/reject')
        rec.observe('testnet4','[tempnet:p2p-observation] peer=1.2.3.4:28333 candidate_height=100 candidate_hash='+'b'*64)
        self.assertTrue(rec.drain(5))
        self.assertEqual(rec.failures,0)
        rec.close()
        p=PeerStore(network_db_path('tempnet_fablous_2026',self.root)).get('1.2.3.4',48335)
        self.assertEqual(p['handshake_ok_count'],1)
        self.assertEqual(p['last_header_height'],359495)
        self.assertEqual(p['broadcast_attempt_count'],1)
        self.assertEqual(p['broadcast_reject_count'],0)
        self.assertEqual(p['runtime_event_count'],7)
        self.assertIsNone(PeerStore(network_db_path('testnet4',self.root)).get('1.2.3.4',48335))
        self.assertEqual(PeerStore(network_db_path('testnet4',self.root)).get('1.2.3.4',28333)['last_header_height'],100)
        with PeerStore(network_db_path('tempnet_fablous_2026',self.root)).connect() as c:
            details=c.execute('SELECT details FROM peer_events WHERE event_type="headers_observed"').fetchone()[0]
            self.assertIn('miner_runtime',details)

    def test_migration_existing_schema_keeps_data(self):
        path=self.root/'existing.sqlite'
        store=PeerStore(path)
        store.add_peer('8.8.8.8',8333,source_type='manual',source_value='original')
        with store.connect() as c:
            c.execute("UPDATE schema_meta SET value='1' WHERE key='version'")
            for table in ('mining_sessions','wallets_for_test'):
                c.execute(f'CREATE TABLE IF NOT EXISTS {table}(label TEXT)')
                c.execute(f'INSERT INTO {table}(label) VALUES (?)',('conservar',))
            # SQLite elimina columnas sólo si versión >= 3.35 (sucede en test).
            for name in ('last_headers_at','last_header_height','last_header_hash','last_chain_compatible_at',
                         'last_chain_incompatible_at','last_miner_event_at','runtime_event_count'):
                c.execute(f'ALTER TABLE peers DROP COLUMN {name}')
        new=PeerStore(path)
        self.assertEqual(new.get('8.8.8.8',8333)['last_header_height'],None)
        with new.connect() as c:
            self.assertEqual(c.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0],'2')
            self.assertEqual(c.execute('SELECT label FROM mining_sessions').fetchone()[0],'conservar')
            self.assertEqual(c.execute('SELECT label FROM wallets_for_test').fetchone()[0],'conservar')
        self.assertEqual(new.integrity()['quick_check'],'ok')

    def test_multiple_writers_from_explorer_and_miner(self):
        store=PeerStore(network_db_path('tempnet_fablous_2026',self.root))
        rec=RuntimePeerRecorder(root=self.root)
        for i in range(40):
            store.add_peer('8.8.8.8',48335,source_type='dns',source_value='seed.test')
            store.record('8.8.8.8',48335,'connect_attempt')
            rec.observe('tempnet_fablous_2026','[tempnet:p2p-observation] peer=8.8.8.8:48335 candidate_height=359495 candidate_hash='+'a'*64)
        self.assertTrue(rec.drain(10))
        rec.close()
        self.assertEqual(rec.failures,0)
        p=store.get('8.8.8.8',48335)
        self.assertEqual(p['handshake_ok_count'],40)
        self.assertEqual(p['tcp_ok_count'],40)
        self.assertEqual(p['runtime_event_count'],200)
        self.assertEqual(store.integrity()['quick_check'],'ok')

if __name__ == '__main__':unittest.main()
