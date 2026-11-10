"""v2.3.2 multi-format wallet, no secrets from the user, no network or Windows DPAPI."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch

from cashminer.wallet.crypto import (ORDER, address_for, address_for_legacy, decode_address,
                                           public_key, hash160, p2pkh_script, sha256d, script_hash)
from cashminer.wallet.store import WalletStore
from cashminer.wallet.transactions import serialize_tx, parse_tx, build_signed, digest_for_input
from cashminer.wallet.sync import scan_wallet

PRIV_ONE = '0' * 63 + '1'  # public, well-known secp256k1 test vector (never a personal key)
MNEMONIC = 'abandon ' * 11 + 'about'
SEED32 = bytes(range(32))
SEED64 = bytes(range(64))

class ElectrumMock:
    host = 'test.local'; port = 50002
    def __init__(self, network, address=None, value=None, height=100):
        self.network = network
        self.address = address
        self.value = value
        self.height = height
        self.calls = {}
        self.notifications = []
        if address and value:
            raw = serialize_tx([{'txid': '00'*32, 'vout':0xffffffff, 'sequence':0xffffffff,'script_sig':b'test'}],
                               [{'value':value,'script':p2pkh_script(decode_address(address,network))}])
            self.raw, self.txid = raw.hex(), sha256d(raw)[::-1].hex()
        else: self.raw, self.txid = None, None
    def tip_height_hash(self):return 300,'b'*64
    def rpc(self, method, params):
        self.calls[method] = self.calls.get(method,0)+1
        match = self.address and params[0]==script_hash(self.address,self.network) if method.endswith(('get_history','listunspent')) else False
        if method=='blockchain.scripthash.subscribe':
            return 'ab'*32 if self.txid and params[0]==script_hash(self.address,self.network) else None
        if method.endswith('get_history'):
            return [{'tx_hash':self.txid,'height':self.height}] if match and self.txid else []
        if method.endswith('listunspent'):
            return [{'tx_hash':self.txid,'tx_pos':0,'value':self.value,'height':self.height}] if match and self.txid else []
        if method=='blockchain.transaction.get':return self.raw
        raise AssertionError('unexpected Electrum method '+method)

class WalletFormats(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Mock is deliberately INSECURE and used only in an isolated temporary test dir.
        p1=patch('cashminer.wallet.store.protect_seed', side_effect=lambda x,w: b'test:'+w.encode()+b'|'+x)
        p2=patch('cashminer.wallet.store.unprotect_seed', side_effect=lambda x,w: x.split(b'|',1)[1])
        p1.start();p2.start()
        self.addCleanup(p1.stop);self.addCleanup(p2.stop)
        self.store=WalletStore('tempnet_fablous_2026',Path(self.tmp.name))

    def test_legacy_matches_original_cashminer_engine_compressed_key(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('cashminer_legacy_wallet_test',root/'mining_engine'/'fablous'/'legacy_reward_wallet.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        address=old.address_for_private_key(1)
        self.assertEqual(address,address_for_legacy(1,'tempnet_fablous_2026',True))
        self.assertNotEqual(address,address_for_legacy(1,'tempnet_fablous_2026',False))
        cands=self.store.legacy_candidates(PRIV_ONE)
        self.assertEqual(cands[0]['address'],address)
        with self.assertRaisesRegex(ValueError,'no coincide'):
            self.store.create('Wrong',legacy_hex=PRIV_ONE,expected_address=cands[1]['address'])
        self.assertEqual(self.store.list(),[])
        w=self.store.create('Original tempnet',legacy_hex=PRIV_ONE,
                            legacy_compressed=True,expected_address=address)
        self.assertEqual(self.store.get(w['id'])['wallet_type'],'legacy-compressed')
        self.assertEqual(self.store.list()[0]['kind'],'legacy')
        self.assertEqual(self.store.legacy_key(w['id']),(1,True))
        self.assertEqual(self.store.recovery(w['id'])['private_key_hex'],PRIV_ONE)
        self.assertEqual(self.store.issue_receive(w['id'])['address'],address)
        self.assertTrue(self.store.issue_receive(w['id'])['reused'])
        self.assertEqual(self.store.issue_receive(w['id'])['address'],address)
        self.assertEqual(self.store.get(w['id'])['receive_index'],0)
        with self.assertRaisesRegex(ValueError,'no es una semilla'):
            self.store.seed(w['id'])
        with self.assertRaisesRegex(ValueError,'dirección fija'):
            self.store.issue_change(w['id'])

    def test_legacy_uncompressed_scans_single_address_and_keeps_coinbase_maturity(self):
        addr=address_for_legacy(1,'tempnet_fablous_2026',False)
        w=self.store.create('Old uncompressed',legacy_hex=PRIV_ONE,
                            legacy_compressed=False,expected_address=addr)
        fake=ElectrumMock('tempnet_fablous_2026',addr,250_000_000,height=280)
        watch={}
        self.assertEqual(scan_wallet(self.store,fake,w['id'],watch),1)
        self.assertEqual(len(watch),1)
        self.assertEqual(self.store.list()[0]['available_sats'],0)
        self.assertEqual(self.store.list()[0]['immature_sats'],250_000_000)
        self.assertEqual(self.store.get(w['id'])['scan_state'],'synced')
        self.assertEqual(len(self.store.spending_utxos(w['id'])),1)

    def test_legacy_signature_compressed_and_uncompressed(self):
        from cryptography.hazmat.primitives.asymmetric import ec,utils
        from cryptography.hazmat.primitives import hashes
        for compressed in (True,False):
            addr=address_for_legacy(1,'tempnet_fablous_2026',compressed)
            destination=address_for_legacy(2,'tempnet_fablous_2026',True)
            utxo={'txid':'ab'*32,'vout':0,'address':addr,'value':300000,'height':120,
                  'branch':0,'idx':0,'tokens':0,'coinbase_immature':False}
            tx=build_signed(None,'tempnet_fablous_2026',[utxo],destination,150000,addr,
                            fee_rate=2,legacy_private=1,legacy_compressed=compressed)
            parsed=parse_tx(tx['raw_hex']);self.assertEqual(tx['txid'],parsed['txid'])
            sigscript=parsed['inputs'][0]['script']
            siglen=sigscript[0];sig=sigscript[1:1+siglen]
            pub=sigscript[2+siglen:]
            self.assertEqual(len(pub),33 if compressed else 65)
            self.assertEqual(hash160(pub),decode_address(addr,'tempnet_fablous_2026'))
            digest=digest_for_input([{'txid':utxo['txid'],'vout':0,'sequence':0xfffffffe}],parsed['outputs'],0,hash160(pub),utxo['value'])
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(),pub).verify(
                sig[:-1],digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            self.assertGreaterEqual(tx['fee_sats'],len(bytes.fromhex(tx['raw_hex']))*2)

    def test_sender_legacy_change_returns_to_same_address(self):
        from cashminer.wallet.send import WalletSender
        addr=address_for_legacy(1,self.store.network,True)
        w=self.store.create('Sender',legacy_hex=PRIV_ONE,expected_address=addr)
        fake=ElectrumMock(self.store.network,addr,500000,height=120)
        scan_wallet(self.store,fake,w['id'],{})
        destination=address_for_legacy(2,self.store.network,True)
        with patch.object(self.store,'issue_change',side_effect=AssertionError('Legacy must not derive HD change')):
            sender=WalletSender()
            summary=sender.prepare(self.store,w['id'],destination,'0.001',fee_rate=2)
        self.assertEqual(summary['network'],self.store.network)
        self.assertEqual(summary['amount_sats'],100000)
        self.assertEqual(sender.previews[summary['token']]['tx']['change_address'],addr)
        self.assertGreater(sender.previews[summary['token']]['tx']['change_sats'],0)

    def test_account_hd_transaction_uses_selected_account(self):
        from cashminer.wallet.transactions import build_signed
        addr=address_for(SEED32,self.store.network,0,0,account=4)
        dest=address_for(SEED32,self.store.network,0,1,account=4)
        utxo={'txid':'a1'*32,'vout':0,'address':addr,'value':500000,'height':120,
              'branch':0,'idx':0,'tokens':0,'coinbase_immature':False}
        built=build_signed(SEED32,self.store.network,[utxo],dest,100000,dest,
                           account_index=4)
        self.assertEqual(parse_tx(built['raw_hex'])['txid'],built['txid'])
        with self.assertRaisesRegex(ValueError,'Clave derivada no coincide'):
            build_signed(SEED32,self.store.network,[utxo],dest,100000,dest,
                         account_index=0)

    def test_legacy_wrong_and_duplicate_keys_are_rejected(self):
        for bad in ('00'*32,'ff'*32,'deadbeef','nothex'):
            with self.assertRaises(ValueError):self.store.legacy_candidates(bad)
        addr=address_for_legacy(1,'tempnet_fablous_2026')
        w=self.store.create('Duplicate check',legacy_hex=PRIV_ONE,expected_address=addr)
        with self.assertRaisesRegex(ValueError,'ya existe'):
            self.store.create('Duplicate',legacy_hex=PRIV_ONE,expected_address=addr)
        self.assertEqual(len(self.store.list()),1)
        # No cross-chain auto-forwarding even though BCH testnets reuse bchtest prefix.
        testnet=WalletStore('testnet3',Path(self.tmp.name))
        self.assertEqual(testnet.list(),[])
        self.assertEqual(testnet.legacy_candidates(PRIV_ONE)[0]['address'],addr)

    def test_account_hd_and_64_byte_hd_seed(self):
        self.assertNotEqual(address_for(SEED64,'testnet3',0,0,account=1),
                            address_for(SEED64,'testnet3',0,0,account=0))
        w=self.store.create('HD 64',recovery_hex=SEED64.hex(),account_index=2)
        self.assertEqual(self.store.get(w['id'])['account_index'],2)
        self.assertEqual(self.store.get(w['id'])['first_address'],address_for(SEED64,self.store.network,0,0,2))
        self.assertEqual(self.store.recovery(w['id'])['seed_hex'],SEED64.hex())
        self.assertEqual(self.store.issue_receive(w['id'])['address'],address_for(SEED64,self.store.network,0,0,2))
        self.assertEqual(self.store.issue_change(w['id'])['address'],address_for(SEED64,self.store.network,1,0,2))
        fake=ElectrumMock(self.store.network)
        self.assertEqual(scan_wallet(self.store,fake,w['id'],{}),42)
        self.assertEqual(self.store.seed(w['id']),SEED64)

    def test_old_cashminer_64_byte_hd_seed_and_path_are_preserved(self):
        from cashminer.wallet import legacy_hd as wallet_hd
        for network in ('mainnet','testnet3','testnet4','tempnet_fablous_2026'):
            for idx in (0,1,7):
                self.assertEqual(wallet_hd.derive_private(SEED64,network,idx),
                                 __import__('cashminer.wallet.crypto',fromlist=['derive_private']).derive_private(SEED64,network,0,idx,0))
                address=wallet_hd.address_from_secret(wallet_hd.derive_private(SEED64,network,idx),network)
                self.assertEqual(address,address_for(SEED64,network,0,idx,0))

    def test_legacy_import_requires_confirmed_address(self):
        with self.assertRaisesRegex(ValueError,'confirmá la dirección'):
            self.store.create('No address',legacy_hex=PRIV_ONE)
        with self.assertRaises(ValueError):
            self.store.create('Not WIF',legacy_hex='L'+PRIV_ONE[:51])

    def test_bip39_short_phrase_and_new_key_types(self):
        w=self.store.create('12 words',mnemonic=MNEMONIC,account_index=3)
        self.assertEqual(self.store.recovery(w['id'])['mnemonic'],MNEMONIC)
        self.assertEqual(self.store.get(w['id'])['account_index'],3)
        w2=self.store.create('new 64 HD',new_type='raw-bip32',seed_bytes=64)
        self.assertEqual(len(self.store.recovery(w2['id'])['seed_hex']),128)
        w3=self.store.create('new legacy',new_type='legacy-hex')
        self.assertEqual(len(self.store.recovery(w3['id'])['private_key_hex']),64)
        self.assertEqual(len(w3['private_key_hex']),64)

    def test_old_sqlite_schema_adds_columns_preserving_wallet_and_vault(self):
        from cashminer.wallet.bip39 import entropy_to_mnemonic
        root=Path(self.tmp.name)/'testnet4';root.mkdir()
        dbpath=root/'wallets.sqlite'
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('CREATE TABLE wallets(id TEXT PRIMARY KEY,name TEXT NOT NULL,first_address TEXT NOT NULL,'
                       'receive_index INTEGER NOT NULL DEFAULT 0,change_index INTEGER NOT NULL DEFAULT 0,'
                       'scan_state TEXT NOT NULL DEFAULT "pending",last_sync TEXT,provider TEXT,tip_height INTEGER,'
                       'tip_hash TEXT,error TEXT,created_at TEXT NOT NULL)')
            db.execute('INSERT INTO wallets(id,name,first_address,created_at) VALUES(?,?,?,?)',
                       ('a'*32,'Existing HD',address_for(SEED32,'testnet4',0,0),'2026-11-07T00:00:00Z'))
        vaults=root/'vaults';vaults.mkdir()
        envelope={'format':'cashminer-v23-dpapi','network':'testnet4','id':'a'*32,'seed_mode':'raw-bip32',
                  'blob':__import__('base64').b64encode(b'test:'+b'a'*32+b'|'+SEED32).decode('ascii')}
        (vaults/('a'*32+'.json')).write_text(json.dumps(envelope))
        store=WalletStore('testnet4',Path(self.tmp.name))
        self.assertEqual(store.get('a'*32)['wallet_type'],'hd')
        self.assertEqual(store.get('a'*32)['account_index'],0)
        self.assertEqual(store.seed('a'*32),SEED32)
        self.assertEqual(store.issue_receive('a'*32)['address'],address_for(SEED32,'testnet4',0,0))
        self.assertEqual(store.get('a'*32)['name'],'Existing HD')

class UIContract(unittest.TestCase):
    def test_modal_network_labels_and_import_choice(self):
        html=(Path(__file__).resolve().parents[1]/'ui'/'index.html').read_text()
        server=(Path(__file__).resolve().parents[1]/'src'/'cashminer'/'app/server.py').read_text()
        self.assertIn("modal('Mis billeteras · '+walletNetLabel",html)
        self.assertNotIn('Red seleccionada: ${esc(current.network_label)}',html)
        self.assertIn('Modo de conexión con la red',html)
        self.assertIn('legacyImportSection',html)
        self.assertIn('Comprobar direcciones',html)
        self.assertIn('private_key_hex:legacyPreview.key',html)
        self.assertIn('expected_address:choice.address',html)
        self.assertIn("'/api/wallet/legacy/preview'",server)
        self.assertIn("if data.get('network') != s.wallet_network:",server)

if __name__=='__main__':unittest.main()
