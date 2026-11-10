"""v2.7.13.1: post-ACK local UTXOs and reconciliation, all offline/testnet.

No live broadcast, Windows keys, or GPU usage. Historical chains are faked
solely to test DB state races and UI safety decisions.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.wallet.store import WalletStore
from cashminer.wallet.send import WalletSender
from cashminer.wallet.sync import scan_wallet
from cashminer.wallet.crypto import (
    address_for_legacy, decode_address, p2pkh_script, script_hash, sha256d)
from cashminer.wallet.transactions import serialize_tx
from cashminer.wallet.electrum import ElectrumError, ElectrumRPCError


class ElectrumOffline:
    host='fake.example';port=50002
    def __init__(self):
        self.states={}
        self.txs={}
        self.notifications=[]
        self.on_history=None
        self.height=1000

    def tip_height_hash(self):return self.height,'a1'*32

    def funding(self, address, value, tag, *, height=500):
        raw=serialize_tx([{'txid':format(tag,'064x'),'vout':0,'sequence':0xffffffff,
                           'script_sig':b'fund'}],
                         [{'value':value,'script':p2pkh_script(decode_address(address,'testnet3'))}])
        txid=sha256d(raw)[::-1].hex()
        self.txs[txid]=raw.hex()
        return {'tx_hash':txid,'tx_pos':0,'height':height,'value':value}, {'tx_hash':txid,'height':height}

    def set_address(self,address,utxos,histories,status):
        self.states[script_hash(address,'testnet3')]={'utxos':utxos,'history':histories,'status':status}

    def rpc(self, method, params):
        if method=='blockchain.transaction.get':return self.txs[params[0]]
        state=self.states.get(params[0],{'status':None,'history':[],'utxos':[]})
        if method=='blockchain.scripthash.subscribe':return state['status']
        if method=='blockchain.scripthash.get_history':
            if self.on_history:
                callback,self.on_history=self.on_history,None
                callback()
            return state['history']
        if method=='blockchain.scripthash.listunspent':
            assert params[1]=='include_tokens'
            return state['utxos']
        raise AssertionError(method)


class PostBroadcast27131(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        p=patch('cashminer.wallet.store.protect_seed',side_effect=lambda raw,w:b'test|'+raw)
        u=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,w:raw[5:])
        p.start();u.start();self.addCleanup(p.stop);self.addCleanup(u.stop)
        self.store=WalletStore('testnet3',Path(tmp.name))
        self.wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
            expected_address=address_for_legacy(1,'testnet3',True))
        self.wid=self.wallet['id']
        self.sender=WalletSender()
        self.client=ElectrumOffline()
        self.source=self.wallet['address']
        self.recipient=address_for_legacy(2,'testnet3',True)
        self.funding_utxo,self.funding_history=self.client.funding(self.source,1_000_000,11)
        self.client.set_address(self.source,[self.funding_utxo],[self.funding_history],'aa'*32)
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000)

    def send(self):
        preview=self.sender.prepare(self.store,self.wid,self.recipient,'0.003','1')
        tx=self.sender.previews[preview['token']]['tx']
        self.client.txs[tx['txid']]=tx['raw_hex']
        with patch.object(self.sender,'_broadcast_to_server',return_value=preview['txid']) as rpc:
            result=self.sender.broadcast(self.store,self.wid,preview['token'])
            rpc.assert_called_once()
        self.assertEqual(result['status'],'sent')
        return preview,tx

    def local_counts(self):
        with self.store.db() as db:
            return (db.execute('SELECT COUNT(*) FROM local_broadcast_inputs').fetchone()[0],
                    db.execute('SELECT COUNT(*) FROM local_broadcast_outputs').fetchone()[0])

    def test_accepted_broadcast_changes_spendable_balance_immediately(self):
        preview,tx=self.send()
        self.assertEqual(self.store.get(self.wid)['scan_state'],'synced')
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000-300_000-preview['fee_sats'])
        utxos=self.store.utxos(self.wid)
        self.assertEqual([(u['txid'],u['vout'],u['value'],u['height']) for u in utxos],
                         [(tx['txid'],1,tx['change_sats'],0)])
        self.assertEqual(self.local_counts(),(1,1))
        with self.store.db() as db:
            rec=db.execute('SELECT raw_hex,state FROM local_transactions WHERE txid=?',
                           (tx['txid'],)).fetchone()
            self.assertEqual((rec['raw_hex'],rec['state']),('','broadcast'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pending_spends').fetchone()[0],0)

    def test_lagging_electrum_does_not_resurrect_spent_inputs(self):
        preview,tx=self.send()
        extra,h_extra=self.client.funding(self.source,123_456,12)
        # Server still reports the OLD input, plus an unrelated incoming UTXO.
        self.client.set_address(self.source,[self.funding_utxo,extra],
                                [self.funding_history,h_extra],'bb'*32)
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual(self.local_counts(),(1,1))
        utxos=self.store.utxos(self.wid)
        self.assertNotIn((self.funding_utxo['tx_hash'],0),{(u['txid'],u['vout']) for u in utxos})
        self.assertEqual(self.store.list()[0]['available_sats'],tx['change_sats']+123_456)
        self.assertEqual(self.store.get(self.wid)['scan_state'],'synced')
        # Once the server's history and UTXO set include our TX, retire overlay.
        change={'tx_hash':tx['txid'],'tx_pos':1,'height':0,'value':tx['change_sats']}
        self.client.set_address(self.source,[change,extra],
                                [self.funding_history,h_extra,{'tx_hash':tx['txid'],'height':0}],
                                'cc'*32)
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual(self.local_counts(),(0,0))
        self.assertEqual(self.store.list()[0]['available_sats'],tx['change_sats']+123_456)

    def test_scan_snapshot_started_before_ack_cannot_restore_old_utxo(self):
        preview=self.sender.prepare(self.store,self.wid,self.recipient,'0.003')
        tx=self.sender.previews[preview['token']]['tx']
        # This incoming payment forces the scanner to reread the old input.
        extra,h_extra=self.client.funding(self.source,33_333,13)
        self.client.set_address(self.source,[self.funding_utxo,extra],
                                [self.funding_history,h_extra],'bb'*32)
        def broadcast_during_scan():
            with patch.object(self.sender,'_broadcast_to_server',return_value=tx['txid']):
                self.assertEqual(self.sender.broadcast(self.store,self.wid,preview['token'])['status'],'sent')
        self.client.on_history=broadcast_during_scan
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual(self.store.list()[0]['available_sats'],tx['change_sats']+33_333)
        self.assertEqual(self.local_counts(),(1,1))
        self.assertEqual(self.store.get(self.wid)['scan_state'],'synced')

    def test_second_prepared_spend_cannot_reuse_inputs(self):
        first=self.sender.prepare(self.store,self.wid,self.recipient,'0.003')
        second=self.sender.prepare(self.store,self.wid,self.recipient,'0.002')
        tx2=self.sender.previews[second['token']]['tx']
        self.assertEqual(self.sender.previews[first['token']]['tx']['input_refs'],tx2['input_refs'])
        with patch.object(self.sender,'_broadcast_to_server',return_value=first['txid']):
            self.assertEqual(self.sender.broadcast(self.store,self.wid,first['token'])['status'],'sent')
        with patch.object(self.sender,'_broadcast_to_server') as rpc:
            with self.assertRaisesRegex(ValueError,'venció'):
                self.sender.broadcast(self.store,self.wid,second['token'])
            rpc.assert_not_called()
        # Even another sender instance with an old signed preview must reject.
        another=WalletSender()
        another.previews['stale']={'deadline':10**20,'wid':self.wid,'network':'testnet3','tx':tx2}
        with patch.object(another,'_broadcast_to_server') as rpc:
            with self.assertRaisesRegex(ValueError,'cambiaron'):
                another.broadcast(self.store,self.wid,'stale')
            rpc.assert_not_called()

    def test_two_local_broadcasts_cannot_resurrect_intermediate_change(self):
        first,first_tx=self.send()
        second=self.sender.prepare(self.store,self.wid,self.recipient,'0.002')
        tx2=self.sender.previews[second['token']]['tx']
        self.assertEqual(tx2['input_refs'],[(first_tx['txid'],1)])
        with patch.object(self.sender,'_broadcast_to_server',return_value=second['txid']):
            self.assertEqual(self.sender.broadcast(self.store,self.wid,second['token'])['status'],'sent')
        self.assertEqual(self.store.list()[0]['available_sats'],tx2['change_sats'])
        self.assertEqual(self.local_counts(),(2,2))
        # An unrelated incoming transfer forces a scan on a server that has not
        # yet observed *either* locally sent transaction.
        extra,history=self.client.funding(self.source,12_345,15)
        self.client.set_address(self.source,[self.funding_utxo,extra],
                                [self.funding_history,history],'bb'*32)
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual({(u['txid'],u['vout']) for u in self.store.utxos(self.wid)},
                         {(tx2['txid'],1),(extra['tx_hash'],0)})
        self.assertEqual(self.store.list()[0]['available_sats'],tx2['change_sats']+12_345)

    def test_self_transfer_credits_both_owned_outputs_and_only_charges_fee(self):
        recipient=self.source
        preview=self.sender.prepare(self.store,self.wid,recipient,'0.002')
        tx=self.sender.previews[preview['token']]['tx']
        with patch.object(self.sender,'_broadcast_to_server',return_value=preview['txid']):
            self.assertEqual(self.sender.broadcast(self.store,self.wid,preview['token'])['status'],'sent')
        rows=self.store.utxos(self.wid)
        self.assertEqual({(r['txid'],r['vout']) for r in rows},
                         {(tx['txid'],0),(tx['txid'],1)})
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000-preview['fee_sats'])
        self.assertEqual(self.local_counts(),(1,2))

    def test_local_projection_survives_restarting_the_wallet_store(self):
        preview,tx=self.send()
        reopened=WalletStore('testnet3',self.store.root)
        self.assertEqual(reopened.list()[0]['available_sats'],tx['change_sats'])
        self.assertEqual(reopened.get(self.wid)['scan_state'],'synced')
        extra,h_extra=self.client.funding(self.source,4567,19)
        self.client.set_address(self.source,[self.funding_utxo,extra],
                                [self.funding_history,h_extra],'bb'*32)
        scan_wallet(reopened,self.client,self.wid,{})
        self.assertEqual(reopened.list()[0]['available_sats'],tx['change_sats']+4567)

    def test_existing_sqlite_database_migrates_without_losing_utxos(self):
        with self.store.db() as db:
            db.execute('DROP TABLE local_broadcast_inputs')
            db.execute('DROP TABLE local_broadcast_outputs')
        reopened=WalletStore('testnet3',self.store.root)
        self.assertEqual(reopened.list()[0]['available_sats'],1_000_000)
        with reopened.db() as db:
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='local_broadcast_inputs'").fetchone())
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='local_broadcast_outputs'").fetchone())

    def test_local_bookkeeping_failure_rolls_back_all_sqlite_changes(self):
        invalid={'txid':'3a'*32,'input_refs':[(self.funding_utxo['tx_hash'],0)],
                 'input_addresses':[self.recipient],
                 'destination':self.recipient,'amount_sats':300000,
                 'change_address':self.source,'change_sats':699000}
        with self.assertRaisesRegex(ValueError,'no pertenece'):
            self.store.note_broadcast(self.wid,invalid)
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000)
        self.assertEqual(self.local_counts(),(0,0))

    def test_incoming_utxo_does_not_mark_synced_wallet_stale(self):
        extra,h_extra=self.client.funding(self.source,55_555,14)
        self.client.set_address(self.source,[self.funding_utxo,extra],
                                [self.funding_history,h_extra],'bb'*32)
        scan_wallet(self.store,self.client,self.wid,{})
        self.assertEqual(self.store.get(self.wid)['scan_state'],'synced')
        self.assertEqual(self.store.list()[0]['available_sats'],1_055_555)

    def test_rejected_preserves_utxos_uncertain_requires_reconciliation(self):
        first=self.sender.prepare(self.store,self.wid,self.recipient,'0.003')
        with patch.object(self.sender,'_broadcast_to_server',side_effect=ElectrumRPCError(
            'blockchain.transaction.broadcast',{'code':-26,'message':'rejected'})):
            self.assertEqual(self.sender.broadcast(self.store,self.wid,first['token'])['status'],'rejected')
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000)
        self.assertEqual(self.store.get(self.wid)['scan_state'],'synced')
        self.assertEqual(self.local_counts(),(0,0))
        second=self.sender.prepare(self.store,self.wid,self.recipient,'0.003')
        with patch.object(self.sender,'_broadcast_to_server',side_effect=ElectrumError('timeout')):
            self.assertEqual(self.sender.broadcast(self.store,self.wid,second['token'])['status'],'uncertain')
        self.assertEqual(self.store.list()[0]['available_sats'],1_000_000)
        self.assertEqual(self.store.get(self.wid)['scan_state'],'stale')
        self.assertEqual(self.local_counts(),(0,0))

    def test_ui_compact_breakdown_and_incoming_live_state(self):
        html=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text('utf8')
        self.assertIn('justify-content:flex-start;align-items:baseline;gap:4px',html)
        self.assertIn('<span class="wallet-detail-long">Saldo total:</span><span class="wallet-detail-short">Total:</span><strong id="balanceTotal">',html)
        self.assertIn('<span class="wallet-detail-long">Recompensas inmaduras:</span><span class="wallet-detail-short">Inmaduras:</span><strong id="balanceImmature">',html)
        self.assertIn("(ws.status==='conectado'||ws.status==='sincronizando')",html)

if __name__=='__main__':unittest.main()
