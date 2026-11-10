"""Structured miner events -> existing SQLite, without public mining."""
import contextlib
import datetime
import io
import json
import os
import queue
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.network.runtime_peers import RuntimePeerRecorder,parse_peer_event,EVENT_PREFIX
from cashminer.network.peer_store import PeerStore
from cashminer.app import server

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine
import broadcast


def event(kind,network='testnet3',ip='1.2.3.4',**fields):
    return EVENT_PREFIX+json.dumps(dict(schema=1,network=network,ip=ip,port=18333,
        ts='2026-11-10T09:00:00+00:00',kind=kind,**fields))


class MinerSQLiteEvents(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.rec=RuntimePeerRecorder(root=self.root,structured=True)
        self.addCleanup(self.rec.close)

    def save(self,*lines,network='testnet3'):
        for line in lines:self.rec.observe(network,line)
        self.assertTrue(self.rec.drain(5));self.assertEqual(self.rec.failures,0)
        return PeerStore(self.root/'networks'/(network+'.sqlite'))

    def test_connection_handshake_metadata_timestamps_and_counts(self):
        st=self.save(event('connect_attempt'),event('tcp_ok'),event('handshake_ok',
            services=33,protocol_version=70016,user_agent='/BCHN/'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['tcp_ok_count'],p['handshake_ok_count'],p['runtime_event_count']),(1,1,3))
        self.assertEqual((p['services'],p['protocol_version'],p['user_agent']),(33,70016,'/BCHN/'))
        self.assertEqual(p['last_attempt_at'],'2026-11-10T09:00:00.000000+00:00')
        self.assertEqual(p['last_miner_event_at'],p['last_attempt_at'])

    def test_transport_failures_are_distinct(self):
        st=self.save(event('tcp_fail',status='refused'),event('handshake_fail',status='wrong magic'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['tcp_fail_count'],p['handshake_fail_count']),(1,1))

    def test_getdata_updates_both_historical_counters_without_log_duplicates(self):
        st=self.save(event('broadcast_attempt'),event('broadcast_result',ok=True,detail='peer pidió el bloque y fue enviado: abc'),
            '[broadcast:OK] 1.2.3.4:18333 -> peer pidió el bloque y fue enviado: abc')
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['broadcast_attempt_count'],p['broadcast_getdata_count'],p['broadcast_headers_ok_count']),(1,1,1))
        self.assertEqual(p['runtime_event_count'],2)

    def test_timeout_mentioning_getdata_and_reject_does_not_count_either(self):
        st=self.save(event('broadcast_result',ok=False,detail='timeout esperando getdata/reject'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['broadcast_getdata_count'],p['broadcast_headers_ok_count'],p['broadcast_reject_count']),(0,0,0))
        with st.connect() as c:
            self.assertEqual(c.execute('SELECT event_type FROM peer_events').fetchone()[0],'broadcast_timeout')

    def test_reject_is_saved_with_reason(self):
        st=self.save(event('broadcast_result',ok=False,detail='reject: bad-prevblk'))
        p=st.get('1.2.3.4',18333);self.assertEqual(p['broadcast_reject_count'],1)
        with st.connect() as c:
            row=c.execute('SELECT details FROM peer_events').fetchone()
        self.assertIn('bad-prevblk',row[0])

    def test_block_sent_is_retained_even_if_peer_later_disconnects_or_rejects(self):
        st=self.save(event('broadcast_result',ok=False,block_sent=True,detail='reject: bad-txn'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['broadcast_getdata_count'],p['broadcast_headers_ok_count'],p['broadcast_reject_count']),(1,1,1))

    def test_headers_announced_does_not_claim_getdata_or_full_acceptance(self):
        st=self.save(event('broadcast_result',ok=True,detail='peer aceptó/anunció headers pero no pidió block: abc'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['broadcast_headers_ok_count'],p['broadcast_getdata_count']),(1,0))

    def test_ipv6_has_same_counters(self):
        st=self.save(event('broadcast_attempt',ip='2001:4860:4860::8888'),
            event('broadcast_result',ip='2001:4860:4860::8888',ok=True,detail='peer pidió el bloque y fue enviado'))
        self.assertEqual(st.get('2001:4860:4860::8888',18333)['broadcast_getdata_count'],1)

    def test_all_networks_are_isolated_including_tempnet_alias(self):
        for n in ('mainnet','testnet3','testnet4','chipnet','regtest','tempnet_fablous_2026'):
            alias='tempnet' if n=='tempnet_fablous_2026' else n
            st=self.save(event('tcp_ok',network=alias),network=n)
            self.assertEqual(st.get('1.2.3.4',18333)['tcp_ok_count'],1)

    def test_peer_seen_restores_actual_source(self):
        st=self.save(event('peer_seen',sources=[dict(type='seed',value='testnet-seed.example')]))
        with st.connect() as c:
            row=c.execute("SELECT source_type,source_value FROM peer_sources WHERE source_type='seed'").fetchone()
        self.assertEqual(tuple(row),('seed','testnet-seed.example'))

    def test_headers_and_post_broadcast_evidence_use_existing_tables(self):
        st=self.save(event('headers_observed',details={'height':123,'hash':'a'*64}),
            event('headers_response',status='post_broadcast_headers',details={'block_hash':'b'*64,'first_hash':'b'*64,'full_consensus':False}))
        p=st.get('1.2.3.4',18333)
        self.assertEqual((p['last_header_height'],p['last_header_hash']),(123,'a'*64))
        with st.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM peer_events WHERE event_type='headers_response'").fetchone()[0],1)

    def test_wrong_network_or_malformed_event_is_rejected(self):
        self.rec.observe('mainnet',event('tcp_ok'))
        self.rec.observe('testnet3',EVENT_PREFIX+'not json')
        self.assertEqual(self.rec.invalid,2)
        self.assertEqual(self.rec.events.qsize(),0)

    def test_tempnet_log_does_not_double_count_structured_handshake(self):
        st=self.save(event('handshake_ok',network='tempnet'),
            event('headers_observed',network='tempnet',details={'height':123,'hash':'a'*64}),
            '[tempnet:p2p-observation] peer=1.2.3.4:18333 candidate_height=123 candidate_hash='+'a'*64,
            network='tempnet_fablous_2026')
        p=st.get('1.2.3.4',18333)
        self.assertEqual(p['handshake_ok_count'],1);self.assertEqual(p['last_header_height'],123)

    def test_metadata_cannot_be_interpreted_as_mining_activity(self):
        class Service:
            sessions={'testnet3':type('Slot',(),{'runtime_recorder':None})()}
            def _log_miner(self,*args):raise AssertionError('Must not parse structured facts as mining log')
        server.CashMinerService.miner_line_for(Service(),'testnet3',event('handshake_ok',user_agent='BLOQUE ENCONTRADO'))

    def test_transient_sqlite_lock_retries_rolled_back_batch_once(self):
        original=PeerStore._record_in_connection
        calls=[]
        def flaky(*args,**kwargs):
            original(*args,**kwargs);calls.append(1)
            if len(calls)==1:raise sqlite3.OperationalError('database is locked')
        with patch.object(PeerStore,'_record_in_connection',new=staticmethod(flaky)):
            st=self.save(event('handshake_ok'))
        self.assertEqual(st.get('1.2.3.4',18333)['handshake_ok_count'],1)
        self.assertEqual(len(calls),2)

    def test_delayed_event_does_not_move_timestamps_backwards(self):
        st=self.save(event('tcp_ok'),event('tcp_ok').replace('2026-11-10','2025-11-10'))
        p=st.get('1.2.3.4',18333)
        self.assertEqual(p['tcp_ok_count'],2)
        self.assertEqual(p['last_tcp_ok_at'],'2026-11-10T09:00:00.000000+00:00')
        self.assertEqual(p['last_miner_event_at'],p['last_tcp_ok_at'])

    def test_slow_database_does_not_block_reader(self):
        entered=threading.Event();release=threading.Event();original=PeerStore.record_many
        def blocked(store,*args,**kwargs):
            entered.set();release.wait(2);return original(store,*args,**kwargs)
        with patch.object(PeerStore,'record_many',new=blocked):
            try:
                self.rec.observe('testnet3',event('tcp_ok'))
                self.assertTrue(entered.wait(1))
                start=time.monotonic()
                for _ in range(100):self.rec.observe('testnet3',event('tcp_ok'))
                self.assertLess(time.monotonic()-start,.3)
            finally:release.set()
            self.assertTrue(self.rec.drain(5))
        self.assertEqual(self.rec.failures,0)


class EngineEventStream(unittest.TestCase):
    def capture(self,action):
        out=io.StringIO()
        with patch.dict(os.environ,{'CASHMINER2_PEER_EVENTS':'1'}),patch.object(engine,'NETWORK','testnet3'),patch.object(engine,'BROADCAST_PEERS',[]),contextlib.redirect_stdout(out):
            engine.start_peer_db_writer_if_enabled()
            try:
                action()
                engine.PEER_EVENT_QUEUE.join()
            finally:engine.stop_peer_db_writer()
        return [line for line in out.getvalue().splitlines() if EVENT_PREFIX in line]

    def test_original_events_are_forwarded_without_postgres(self):
        lines=self.capture(lambda:engine.emit_peer_seen('1.2.3.4:18333',source_type='seed',source_value='seed.example'))
        self.assertEqual(parse_peer_event(lines[0],'testnet3')[0].kind,'peer_seen')

    def test_broadcaster_owns_transport_facts_without_double_original_calls(self):
        peer=broadcast.PeerTarget('1.2.3.4',18333)
        def action():
            bc=broadcast.BlockBroadcaster(network='testnet')
            engine.emit_peer_connect_attempt('1.2.3.4:18333')
            with patch.object(broadcast.socket,'create_connection',return_value=type('Sock',(),{'settimeout':lambda *_:None})()):bc.connect(peer)
            engine.emit_peer_tcp_ok('1.2.3.4:18333')
            with patch.object(bc,'_handshake_impl',return_value={'services':1}):bc._handshake(None,peer)
            engine.emit_peer_handshake_ok('1.2.3.4:18333',services=1)
        lines=self.capture(action)
        self.assertEqual([parse_peer_event(x,'testnet3')[0].kind for x in lines],['connect_attempt','tcp_ok','handshake_ok'])

    def test_connect_and_handshake_errors_keep_network_semantics(self):
        peer=broadcast.PeerTarget('1.2.3.4',18333)
        def action():
            bc=broadcast.BlockBroadcaster(network='testnet')
            with patch.object(broadcast.socket,'create_connection',side_effect=ConnectionRefusedError('refused')),self.assertRaises(ConnectionRefusedError):bc.connect(peer)
            with patch.object(bc,'_handshake_impl',side_effect=broadcast.HandshakeError('bad handshake')),self.assertRaises(broadcast.HandshakeError):bc._handshake(None,peer)
        self.assertEqual([parse_peer_event(x,'testnet3')[0].kind for x in self.capture(action)],['connect_attempt','tcp_fail','handshake_fail'])

    def test_legacy_timeout_classifier_is_corrected(self):
        self.assertEqual(engine._classify_broadcast_detail(False,'timeout esperando getdata/reject'),'timeout')
        self.assertEqual(engine._classify_broadcast_detail(False,'reject bad-txn'),'reject')

    def test_actual_broadcaster_retains_send_fact_after_disconnect(self):
        from unittest.mock import Mock
        bc=broadcast.BlockBroadcaster(network='testnet');peer=broadcast.PeerTarget('1.2.3.4',18333)
        block=bytes(80);payload=broadcast.build_inv_payload(2,broadcast.block_hash_le_from_block(block))
        with patch.object(bc,'connect',return_value=Mock()),patch.object(bc,'_handshake'),patch.object(bc,'_send'),patch.object(broadcast,'read_message',side_effect=[('getdata',payload),ConnectionError('closed after block')]):
            result=bc.announce_block(peer,block)
        self.assertFalse(result.ok);self.assertTrue(result.block_sent)

    def test_failed_block_send_is_not_recorded_as_sent(self):
        from unittest.mock import Mock
        bc=broadcast.BlockBroadcaster(network='testnet');peer=broadcast.PeerTarget('1.2.3.4',18333)
        block=bytes(80);payload=broadcast.build_inv_payload(2,broadcast.block_hash_le_from_block(block))
        def send(sock,command,*args):
            if command=='block':raise ConnectionError('send failed')
        with patch.object(bc,'connect',return_value=Mock()),patch.object(bc,'_handshake'),patch.object(bc,'_send',side_effect=send),patch.object(broadcast,'read_message',return_value=('getdata',payload)):
            result=bc.announce_block(peer,block)
        self.assertFalse(result.ok);self.assertFalse(result.block_sent)

    def test_full_engine_queue_drops_with_counter_without_blocking_producer(self):
        q=queue.Queue(maxsize=1);q.put({})
        with patch.object(engine,'PEER_EVENT_STREAM',True),patch.object(engine,'PEER_EVENT_QUEUE',q),patch.object(engine,'_PEER_EVENT_DROP_COUNT',0),patch.object(engine,'log') as log:
            engine._emit_peer_event({'kind':'peer_seen'})
            self.assertEqual(engine._PEER_EVENT_DROP_COUNT,1);log.assert_not_called()

    def test_tempnet_existing_getaddr_records_result_and_source(self):
        from fablous import headers
        import struct
        payload=b'\x01'+bytes(12)+bytes(10)+b'\xff\xff'+bytes([8,8,8,8])+struct.pack('>H',48333)
        facts=[]
        with patch.object(broadcast,'PEER_EVENT_SINK',facts.append),patch.object(broadcast.BlockBroadcaster,'connect',return_value=type('Sock',(),{'close':lambda *_:None})()),patch.object(broadcast.BlockBroadcaster,'_handshake'),patch.object(broadcast.BlockBroadcaster,'_send'),patch.object(headers,'read_message',return_value=('addr',payload)):
            candidates=headers.TempnetHeaderClient().discover_from_peer('1.2.3.4:48333')
        self.assertEqual(candidates,['8.8.8.8:48333'])
        self.assertEqual([f['kind'] for f in facts],['addr_ok','peer_seen'])
        self.assertEqual(facts[1]['sources'],[{'type':'peer','value':'1.2.3.4:48333'}])

    def test_tempnet_getaddr_timeout_records_failure(self):
        from fablous import headers
        facts=[]
        with patch.object(broadcast,'PEER_EVENT_SINK',facts.append),patch.object(broadcast.BlockBroadcaster,'connect',return_value=type('Sock',(),{'close':lambda *_:None})()),patch.object(broadcast.BlockBroadcaster,'_handshake'),patch.object(broadcast.BlockBroadcaster,'_send'),patch.object(headers,'read_message',side_effect=socket.timeout()):
            self.assertEqual(headers.TempnetHeaderClient().discover_from_peer('1.2.3.4:48333'),[])
        self.assertEqual([f['kind'] for f in facts],['addr_fail'])

    def test_real_child_local_handshake_and_sqlite_pipeline(self):
        from cashminer.network.p2p import version_payload
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
        port=listener.getsockname()[1]
        def serve():
            try:
                conn,_=listener.accept()
                with conn:
                    conn.settimeout(5)
                    broadcast.read_message(conn,broadcast.NETWORKS['testnet']['magic'])
                    packet=broadcast.build_message(broadcast.NETWORKS['testnet']['magic'],'version',version_payload('127.0.0.1',port))
                    conn.sendall(packet+broadcast.build_message(broadcast.NETWORKS['testnet']['magic'],'verack',b''))
                    broadcast.read_message(conn,broadcast.NETWORKS['testnet']['magic'])
            finally:listener.close()
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        code="""import miner,broadcast
miner.NETWORK='testnet3';miner.BROADCAST_PEERS=[]
miner.start_peer_db_writer_if_enabled()
try:
 b=broadcast.BlockBroadcaster(network='testnet');p=broadcast.PeerTarget('127.0.0.1',PORT)
 with b.connect(p) as s:b._handshake(s,p)
 miner.emit_peer_broadcast_attempt('127.0.0.1:PORT')
 miner.emit_peer_broadcast_result('127.0.0.1:PORT',detail='peer pidió el bloque y fue enviado',ok=True)
finally:miner.stop_peer_db_writer()
""".replace('PORT',str(port))
        env=os.environ.copy();env.update(CASHMINER2_PEER_EVENTS='1',PYTHONIOENCODING='utf8',PYTHONDONTWRITEBYTECODE='1')
        child=subprocess.run([sys.executable,'-c',code],cwd=ROOT/'mining_engine',env=env,capture_output=True,text=True,encoding='utf8',timeout=10,check=True)
        thread.join(3)
        with tempfile.TemporaryDirectory() as td:
            rec=RuntimePeerRecorder(root=Path(td),structured=True)
            try:
                for line in child.stdout.splitlines():rec.observe('testnet3',line)
                self.assertTrue(rec.drain(5));self.assertEqual(rec.invalid,0);self.assertEqual(rec.failures,0)
            finally:rec.close()
            st=PeerStore(Path(td)/'networks/testnet3.sqlite');p=st.get('127.0.0.1',port)
            self.assertEqual((p['tcp_ok_count'],p['handshake_ok_count'],p['protocol_version']),(1,1,70016))
            self.assertEqual((p['broadcast_attempt_count'],p['broadcast_getdata_count'],p['broadcast_headers_ok_count']),(1,1,1))


if __name__=='__main__':unittest.main()
