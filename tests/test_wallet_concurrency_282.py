"""2.8.2: deterministic Electrum pipelining, gap discovery, and unique totals."""
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.wallet.electrum import ElectrumClient, ELECTRUM_MAX_CONCURRENT_REQUESTS
from cashminer.wallet.store import WalletStore
from cashminer.wallet.sync import scan_wallet


class ElectrumPipelineTests(unittest.TestCase):
    def test_out_of_order_replies_and_interleaved_notifications(self):
        client_sock,server_sock=socket.socketpair()
        self.addCleanup(client_sock.close)
        self.addCleanup(server_sock.close)
        client_sock.settimeout(3)
        server_sock.settimeout(3)
        client=ElectrumClient('testnet3','test.invalid',50002,timeout=3)
        client.sock=client_sock
        server_errors=[]
        def server():
            try:
                reader=server_sock.makefile('rb')
                incoming=[json.loads(reader.readline()) for _ in range(8)]
                # Deliberately deliver a notification before reverse-ordered replies.
                event={'jsonrpc':'2.0','method':'blockchain.scripthash.subscribe',
                       'params':['aa'*32,'bb'*32]}
                server_sock.sendall((json.dumps(event)+'\n').encode())
                for request in reversed(incoming):
                    response={'jsonrpc':'2.0','id':request['id'],
                              'result':request['params'][0]*10}
                    server_sock.sendall((json.dumps(response)+'\n').encode())
                # No orphan response may remain after rpc_many.
                req=json.loads(reader.readline())
                server_sock.sendall((json.dumps({'id':req['id'],'result':'pong'})+'\n').encode())
            except Exception as exc:
                server_errors.append(exc)
        worker=threading.Thread(target=server,daemon=True)
        worker.start()
        data=client.rpc_many([('wallet.test',[i]) for i in range(8)])
        self.assertEqual(data,[i*10 for i in range(8)])
        self.assertEqual(client.notifications,[('aa'*32,'bb'*32)])
        self.assertEqual(client.rpc('server.ping',[]),'pong')
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(server_errors,[])

    def test_error_after_pipelined_batch_does_not_leave_orphan_replies(self):
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        a.settimeout(3);b.settimeout(3)
        client=ElectrumClient('testnet3','test.invalid',50002,timeout=3);client.sock=a
        failures=[]
        def server():
            try:
                reader=b.makefile('rb')
                incoming=[json.loads(reader.readline()) for _ in range(2)]
                for req in reversed(incoming):
                    value={'id':req['id'],'result':None if req['params'][0]==1 else 123,
                           'error':{'code':-1,'message':'error'} if req['params'][0]==1 else None}
                    b.sendall((json.dumps(value)+'\n').encode())
            except Exception as exc:failures.append(exc)
        t=threading.Thread(target=server,daemon=True);t.start()
        with self.assertRaisesRegex(Exception,'Electrum'):
            client.rpc_many([('test.x',[0]),('test.x',[1])])
        t.join(3)
        self.assertEqual(failures,[])
        self.assertEqual(client._recvbuf,b'')


class WalletPipelineAndTotals(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)
        a=patch('cashminer.wallet.store.protect_seed',side_effect=lambda raw,wid:b'TEST:'+raw)
        b=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,wid:raw[5:])
        a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
        self.store=WalletStore('testnet3',self.path)

    def test_gap_scan_uses_bounded_pipelining_not_sequential_rpc(self):
        w=self.store.create('Test wallet',recovery_hex='11'*32)
        class EmptyClient:
            host='test.invalid';port=50002
            def __init__(self):self.notifications=[];self.groups=[]
            def rpc_many(self, calls):
                self.groups.append(len(calls))
                if not all(method=='blockchain.scripthash.subscribe' for method,_ in calls):
                    raise AssertionError('Invalid method')
                return [None for _ in calls]
            def rpc(self, method,params):
                raise AssertionError('Should use pipelining for status checks')
            def tip_height_hash(self):return (100,'a'*64)
        client=EmptyClient()
        count=scan_wallet(self.store,client,w['id'],{},set())
        self.assertEqual(count,40)
        self.assertGreater(len(client.groups),1)
        self.assertLessEqual(max(client.groups),ELECTRUM_MAX_CONCURRENT_REQUESTS)
        self.assertEqual(sum(client.groups),40)
        self.assertEqual(self.store.get(w['id'])['scan_state'],'synced')

    def test_unique_total_deduplicates_imported_overlapping_outputs(self):
        a=self.store.create('First',recovery_hex='11'*32)
        b=self.store.create('Second',recovery_hex='22'*32)
        with self.store.db() as db:
            for wid,txid,vout,value in [(a['id'],'aa'*32,0,1000),
                                         (b['id'],'aa'*32,0,1000),
                                         (b['id'],'bb'*32,1,2000)]:
                db.execute('INSERT INTO utxos(wallet_id,txid,vout,address,value,height,coinbase,tokens) VALUES(?,?,?,?,?,1,0,0)',
                           (wid,txid,vout,'addr',value))
            db.execute("UPDATE wallets SET scan_state='synced',last_sync='2026-11-08T12:00:00Z'")
        w=self.store.list()
        self.assertEqual([r['total_sats'] for r in w],[1000,3000])
        summary=self.store.total_unique(w)
        self.assertEqual(summary['total_sats'],3000)
        self.assertEqual(summary['available_sats'],3000)
        self.assertTrue(summary['complete'])
        with self.store.db() as db:
            db.execute("UPDATE wallets SET scan_state='pending' WHERE id=?",(b['id'],))
        self.assertFalse(self.store.total_unique(self.store.list())['complete'])

    def test_unique_available_excludes_immature_coinbase_and_tokens(self):
        a=self.store.create('Mine',recovery_hex='11'*32)
        b=self.store.create('Also mine',recovery_hex='22'*32)
        with self.store.db() as db:
            for wid,txid,value,height,coinbase,tokens in [
                (a['id'],'aa'*32,7_000,901,1,0),  # mature at height 1000
                (a['id'],'bb'*32,4_000,902,1,0),  # 99 confirmations
                (a['id'],'cc'*32,3_000,900,0,1),  # token-bearing output
                (b['id'],'aa'*32,7_000,901,1,0),  # imported duplicate
                (b['id'],'dd'*32,2_000,990,0,0),
            ]:
                db.execute('INSERT INTO utxos(wallet_id,txid,vout,address,value,height,coinbase,tokens) '
                           'VALUES(?,?,?,?,?,?,?,?)',
                           (wid,txid,0,'addr',value,height,coinbase,tokens))
            db.execute("UPDATE wallets SET scan_state='synced',last_sync='2026-11-08T12:00:00Z',tip_height=1000")
        wallets=self.store.list()
        self.assertEqual([w['available_sats'] for w in wallets],[7_000,9_000])
        summary=self.store.total_unique(wallets)
        self.assertEqual(summary['total_sats'],16_000)
        self.assertEqual(summary['available_sats'],9_000)
        self.assertTrue(summary['complete'])

    def test_conflicting_maturity_never_overstates_unique_spendable(self):
        a=self.store.create('Old tip',recovery_hex='11'*32)
        b=self.store.create('New tip',recovery_hex='22'*32)
        with self.store.db() as db:
            for wid in [a['id'],b['id']]:
                db.execute('INSERT INTO utxos(wallet_id,txid,vout,address,value,height,coinbase,tokens) '
                           'VALUES(?,?,?,?,?,?,1,0)',(wid,'aa'*32,0,'addr',6_000,925))
            db.execute("UPDATE wallets SET scan_state='synced',last_sync='2026-11-08T12:00:00Z'")
            db.execute('UPDATE wallets SET tip_height=? WHERE id=?',(1000,a['id']))
            db.execute('UPDATE wallets SET tip_height=? WHERE id=?',(1050,b['id']))
        summary=self.store.total_unique(self.store.list())
        self.assertEqual(summary['total_sats'],6_000)
        self.assertEqual(summary['available_sats'],0)
        self.assertFalse(summary['complete'])

    def test_wallet_selection_receive_is_sticky_until_address_used(self):
        w=self.store.create('Receive test',recovery_hex='11'*32)
        a=self.store.issue_receive(w['id'])
        self.assertEqual(self.store.issue_receive(w['id'])['address'],a['address'])
        self.assertEqual(self.store.list()[0]['receive_used_count'],0)
        with self.store.db() as db:
            db.execute('UPDATE addresses SET used=1 WHERE wallet_id=? AND branch=0 AND idx=0',(w['id'],))
        self.assertEqual(self.store.list()[0]['receive_used_count'],1)
        self.assertNotEqual(self.store.issue_receive(w['id'])['address'],a['address'])

    def test_inline_layout_has_no_receive_button_or_modal(self):
        html=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text('utf8')
        self.assertIn('id="walletReceiveQr"',html)
        self.assertIn('id="walletReceiveAddress"',html)
        self.assertIn('id="walletAggregateAmount"',html)
        self.assertIn('walletReceiveAddress\').onclick',html)
        self.assertIn('new QRCode($(\'walletReceiveQr\')',html)
        self.assertNotIn('id="receiveBtn"',html)
        self.assertNotIn('id="copyReceive"',html)
        self.assertNotIn('modal(\'Recibir ',html)

if __name__=='__main__':unittest.main()
