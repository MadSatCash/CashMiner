"""CashMiner 2.7.7: offline, deterministic incremental BCH wallet regression tests."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.wallet.crypto import (address_for, address_for_legacy,
    script_hash, p2pkh_script, decode_address, sha256d)
from cashminer.wallet.store import WalletStore
from cashminer.wallet.transactions import serialize_tx, locking_script_without_tokens
from cashminer.wallet.sync import scan_wallet, WalletScanStale
from cashminer.wallet.send import WalletSender

SEED=bytes(range(32))


class ElectrumScript:
    host='fake.fulcrum'
    port=50002
    def __init__(self, network='testnet4'):
        self.network=network
        self.states={}
        self.txs={}
        self.calls=[]
        self.notifications=[]
        self.height=1000
        self.blockhash='aa'*32
        self.on_history=None

    def add_output(self,address,value=123456, height=300, coinbase=False, tokens=False):
        pkh=decode_address(address,self.network)
        script=p2pkh_script(pkh)
        if tokens:script=b'\xef'+b'\x01'*32+b'\x10'+b'\x01'+script
        prev='00'*32 if coinbase else '01'*32
        idx=0xffffffff if coinbase else 0
        raw=serialize_tx([{'txid':prev,'vout':idx,'sequence':0xffffffff,'script_sig':b'one'}],
                         [{'value':value,'script':script}])
        txid=sha256d(raw)[::-1].hex()
        sh=script_hash(address,self.network)
        self.txs[txid]=raw.hex()
        self.states[sh]={'status':'ab'*32,
                         'history':[{'tx_hash':txid,'height':height}],
                         'utxos':[{'tx_hash':txid,'tx_pos':0,'height':height,'value':value,
                                   **({'token_data':{'category':'01'*32}} if tokens else {})}]}
        return sh,txid

    def tip_height_hash(self):return self.height,self.blockhash

    def rpc(self,method,params):
        self.calls.append((method,tuple(params)))
        if method=='blockchain.transaction.get':return self.txs[params[0]]
        sh=params[0]
        state=self.states.get(sh,{'status':None,'history':[],'utxos':[]})
        if method=='blockchain.scripthash.subscribe':return state['status']
        if method=='blockchain.scripthash.get_history':
            if self.on_history:self.on_history(sh)
            return state['history']
        if method=='blockchain.scripthash.listunspent':
            assert params[1]=='include_tokens'
            return state['utxos']
        raise AssertionError(method)

    def count(self,method):return sum(m==method for m,_ in self.calls)


class Incremental277(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        a=patch('cashminer.wallet.store.protect_seed',side_effect=lambda s,w:b'test|'+s)
        b=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda v,w:v.split(b'|',1)[1])
        a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
        self.store=WalletStore('testnet4',self.root)
        self.fake=ElectrumScript()

    def test_cached_447_like_utxos_never_redownload_on_reconnect(self):
        wallet=self.store.create('HD',recovery_hex=SEED.hex())
        sh,txid=self.fake.add_output(wallet['address'],value=123456,coinbase=False)
        watch={}
        self.assertEqual(scan_wallet(self.store,self.fake,wallet['id'],watch),41)
        self.assertEqual(self.fake.count('blockchain.transaction.get'),1)
        self.assertEqual(self.store.list()[0]['available_sats'],123456)
        self.fake.calls.clear()
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.fake.count('blockchain.transaction.get'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.get_history'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.listunspent'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.subscribe'),41)
        assert self.store.path == self.root/'testnet4'/'wallets.sqlite'
        assert WalletStore('testnet3',self.root).list()==[]
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM address_history').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT status_known FROM addresses WHERE idx=0 AND branch=0').fetchone()[0],1)

    def test_447_distinct_mining_rewards_download_once_then_zero(self):
        wallet=self.store.create('HD',recovery_hex=SEED.hex())
        address=wallet['address']
        sh=script_hash(address,'testnet4')
        script=p2pkh_script(decode_address(address,'testnet4'))
        history=[];outputs=[]
        for index in range(447):
            raw=serialize_tx([{'txid':'00'*32,'vout':0xffffffff,'sequence':0xffffffff,
                               'script_sig':index.to_bytes(4,'little')}],
                             [{'value':19_531_250,'script':script}])
            txid=sha256d(raw)[::-1].hex()
            self.fake.txs[txid]=raw.hex()
            history.append({'tx_hash':txid,'height':400+index})
            outputs.append({'tx_hash':txid,'tx_pos':0,'value':19_531_250,'height':400+index})
        self.fake.states[sh]={'status':'12'*32,'history':history,'utxos':outputs}
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.fake.count('blockchain.transaction.get'),447)
        self.assertEqual(self.store.list()[0]['utxo_count'],447)
        self.fake.calls.clear()
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.fake.count('blockchain.transaction.get'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.get_history'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.listunspent'),0)
        self.assertEqual(self.fake.count('blockchain.scripthash.subscribe'),41)

    def test_mempool_spend_replaces_utxo_set_without_local_reserves(self):
        wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
                                 expected_address=address_for_legacy(1,'testnet4',True))
        sh,txid=self.fake.add_output(wallet['address'],value=500000)
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.store.list()[0]['available_sats'],500000)
        self.fake.calls.clear()
        self.fake.states[sh]['status']='bc'*32
        self.fake.states[sh]['history'].append({'tx_hash':'23'*32,'height':0})
        self.fake.states[sh]['utxos']=[]
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.store.utxos(wallet['id']),[])
        self.assertEqual(self.store.list()[0]['total_sats'],0)
        self.assertEqual(self.fake.count('blockchain.transaction.get'),0)
        self.assertEqual(len(self.store.history(wallet['id'])),2)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending_spends').fetchone()[0],0)

    def test_new_block_height_updates_from_cache_without_new_tx_download(self):
        wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
                                 expected_address=address_for_legacy(1,'testnet4',True))
        sh,txid=self.fake.add_output(wallet['address'],value=500000,height=990,coinbase=True)
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.store.list()[0]['immature_sats'],500000)
        self.fake.states[sh]['status']='cd'*32
        self.fake.states[sh]['history'][0]['height']=990
        self.fake.states[sh]['utxos'][0]['height']=990
        self.fake.calls.clear()
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.fake.count('blockchain.transaction.get'),0)
        self.assertEqual(self.store.utxos(wallet['id'])[0]['coinbase'],1)

    def test_status_race_rolls_back_entire_wallet(self):
        wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
                                 expected_address=address_for_legacy(1,'testnet4',True))
        sh,txid=self.fake.add_output(wallet['address'])
        def mutate(arg):
            self.fake.states[arg]['status']='bb'*32
            self.fake.notifications.append((arg,'bb'*32))
            self.fake.on_history=None
        self.fake.on_history=mutate
        with self.assertRaises(WalletScanStale):scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.store.get(wallet['id'])['scan_state'],'pending')
        self.assertEqual(self.store.utxos(wallet['id']),[])
        scan_wallet(self.store,self.fake,wallet['id'],{})
        self.assertEqual(self.store.list()[0]['available_sats'],123456)

    def test_cash_token_locked_output_is_recorded_but_not_spendable(self):
        wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
                                 expected_address=address_for_legacy(1,'testnet4',True))
        sh,txid=self.fake.add_output(wallet['address'],value=1500,tokens=True)
        scan_wallet(self.store,self.fake,wallet['id'],{})
        result=self.store.list()[0]
        self.assertEqual(result['total_sats'],1500)
        self.assertEqual(result['token_locked_sats'],1500)
        self.assertEqual(result['available_sats'],0)
        self.assertEqual(self.store.utxos(wallet['id'])[0]['tokens'],1)
        with self.assertRaises(ValueError):locking_script_without_tokens(b'\xef\x00')

    def test_ordinary_zero_conf_receipt_is_available_and_spendable(self):
        wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',
                                 expected_address=address_for_legacy(1,'testnet4',True))
        sh,txid=self.fake.add_output(wallet['address'],value=500000,height=0)
        scan_wallet(self.store,self.fake,wallet['id'],{})
        row=self.store.list()[0]
        self.assertEqual(row['unconfirmed_sats'],500000)
        self.assertEqual(row['available_sats'],500000)
        sender=WalletSender()
        recipient=address_for_legacy(2,'testnet4',True)
        preview=sender.prepare(self.store,wallet['id'],recipient,'0.001')
        self.assertTrue(preview['txid'])
        with patch.object(WalletSender,'_broadcast_to_server',return_value=preview['txid']):
            sender.broadcast(self.store,wallet['id'],preview['token'])
        self.assertNotIn((txid,0),{(u['txid'],u['vout']) for u in self.store.utxos(wallet['id'])})
        self.assertEqual(self.store.get(wallet['id'])['scan_state'],'synced')
        self.assertEqual(self.store.list()[0]['available_sats'],500000-preview['amount_sats']-preview['fee_sats'])
        self.assertEqual(self.store.list()[0]['outgoing_reserved_sats'],0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending_spends').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT raw_hex FROM local_transactions').fetchone()[0],'')

    def test_address_history_union_preserved_when_one_address_changes(self):
        wallet=self.store.create('HD',recovery_hex=SEED.hex())
        addresses=[address_for(SEED,'testnet4',0,i) for i in (0,1)]
        rows=[{'branch':0,'idx':i,'address':address,'scripthash':script_hash(address,'testnet4'),
               'used':1,'issued':1,'electrum_status':'ab'*32}
              for i,address in enumerate(addresses)]
        changes=[{**r,'utxos':[],'history':[{'txid':'ab'*32,'height':10}]} for r in rows]
        self.store.apply_incremental(wallet['id'],rows,changes,100,'cc'*32,'test')
        self.assertEqual(len(self.store.history(wallet['id'])),1)
        rows[0]['electrum_status']=None
        self.store.apply_incremental(wallet['id'],rows,[{**rows[0],'utxos':[],'history':[]}],101,'dd'*32,'test')
        self.assertEqual(len(self.store.history(wallet['id'])),1)
        self.store.apply_incremental(wallet['id'],rows,[{**rows[1],'utxos':[],'history':[]}],102,'ee'*32,'test')
        self.assertEqual(self.store.history(wallet['id']),[])

    def test_migration_backups_existing_wallet_db_and_preserves_keys(self):
        wallet=self.store.create('HD',recovery_hex=SEED.hex())
        # A v2.7.6 legacy-looking DB: SQLite table without the new status fields.
        self.store.path.unlink()  # no live connection; test isolated
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.executescript('''CREATE TABLE wallets (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,first_address TEXT NOT NULL,
                receive_index INTEGER NOT NULL DEFAULT 0,change_index INTEGER NOT NULL DEFAULT 0,
                scan_state TEXT NOT NULL DEFAULT 'pending',last_sync TEXT,provider TEXT,
                tip_height INTEGER,tip_hash TEXT,error TEXT,created_at TEXT NOT NULL,
                wallet_type TEXT NOT NULL DEFAULT 'hd',account_index INTEGER NOT NULL DEFAULT 0,
                derivation_coin_type INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE addresses(wallet_id TEXT NOT NULL,branch INTEGER NOT NULL,idx INTEGER NOT NULL,
                 address TEXT NOT NULL,scripthash TEXT NOT NULL,issued INTEGER NOT NULL DEFAULT 0,
                 used INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(wallet_id,branch,idx));''')
            db.execute('INSERT INTO wallets(id,name,first_address,created_at,wallet_type,derivation_coin_type) VALUES(?,?,?,?,?,?)',
                       (wallet['id'],'HD',wallet['address'],'2026-11-08T00:00:00Z','raw-bip32',1))
        upgraded=WalletStore('testnet4',self.root)
        self.assertEqual(upgraded.seed(wallet['id']),SEED)
        self.assertTrue((upgraded.dir/'wallets.sqlite.pre_v277.bak').is_file())
        with upgraded.db() as db:
            self.assertIn('status_known',{r['name'] for r in db.execute('PRAGMA table_info(addresses)')})

    def test_ui_bip39_choice_closed_and_renamed(self):
        html=(Path(__file__).resolve().parents[1]/'ui'/'index.html').read_text()
        self.assertIn('<details><summary>Frase semilla de 12, 15, 18, 21 o 24 palabras · BIP39</summary>',html)
        self.assertNotIn('<details open><summary>BIP39 · frase',html)

if __name__=='__main__':unittest.main()
