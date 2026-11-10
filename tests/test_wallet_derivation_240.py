"""v2.4: BIP44 account paths, per-wallet persistence and non-destructive migration."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from cashminer.wallet.derivation import (
    parse_account_path, account_path, default_account_path, historical_account_path)
from cashminer.wallet.crypto import address_for, decode_address
from cashminer.wallet.bip39 import mnemonic_to_seed
from cashminer.wallet.store import WalletStore
from cashminer.wallet.sync import scan_wallet
from cashminer.wallet.transactions import build_signed, parse_tx

WORDS = 'abandon ' * 11 + 'about'  # Public BIP39 test vector, not a private wallet.
SEED = mnemonic_to_seed(WORDS)


class EmptyElectrum:
    host, port = 'mock.invalid', 62002
    notifications = []

    def tip_height_hash(self):
        return (300, 'b' * 64)

    def rpc(self, method, params):
        if method=='blockchain.scripthash.subscribe':
            return None
        if method in ('blockchain.scripthash.get_history', 'blockchain.scripthash.listunspent'):
            return []
        raise AssertionError(method)


class Derivation240(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p1 = patch('cashminer.wallet.store.protect_seed', side_effect=lambda x,w: b'mock:' + w.encode() + b'|' + x)
        p2 = patch('cashminer.wallet.store.unprotect_seed', side_effect=lambda x,w: x.split(b'|',1)[1])
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        self.store = WalletStore('testnet4', Path(self.tmp.name))

    def test_defaults_and_parse_restrictions(self):
        for net in ('mainnet','testnet3','testnet4'):
            self.assertEqual(default_account_path(net), "m/44'/145'/0'")
        self.assertEqual(default_account_path('tempnet_fablous_2026'), "m/44'/1'/0'")
        self.assertEqual(historical_account_path('testnet4'), "m/44'/1'/0'")
        self.assertEqual(parse_account_path("m/44'/145'/7'"), (145,7))
        for value in ("m/44'/145'/0'/0/0", "m/49'/145'/0'", "m/44'/145'/1001'",
                      "m/44'/-1'/0'", "m/44'/2147483648'/0'", None, "m/44'/145'/0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_account_path(value)

    def test_import_stores_path_and_matches_bch_coin_type(self):
        w = self.store.create('BIP39 BCH T4', mnemonic=WORDS, derivation_path="m/44'/145'/0'")
        stored = self.store.get(w['id'])
        self.assertEqual(stored['derivation_coin_type'], 145)
        self.assertEqual(stored['derivation_path'], "m/44'/145'/0'")
        self.assertEqual(stored['first_address'], address_for(SEED,'testnet4',0,0,0,145))
        self.assertNotEqual(stored['first_address'], address_for(SEED,'testnet4',0,0))
        self.assertEqual(decode_address(stored['first_address'],'testnet4'),
                         decode_address(address_for(SEED,'mainnet',0,0),'mainnet'))
        self.assertEqual(self.store.recovery(w['id'])['derivation_path'],"m/44'/145'/0'")
        self.assertEqual(self.store.issue_receive(w['id'])['address'],
                         address_for(SEED,'testnet4',0,0,0,145))
        self.assertEqual(self.store.issue_change(w['id'])['address'],
                         address_for(SEED,'testnet4',1,0,0,145))
        scanned = scan_wallet(self.store,EmptyElectrum(),w['id'],{})
        self.assertEqual(scanned,42)  # receive/change address #0 were issued
        self.assertTrue(all(self.store.get(w['id'])['derivation_coin_type']==145 for _ in range(2)))

    def test_path_is_per_wallet_and_old_defaults_remain_accessible(self):
        old = self.store.create('existing from 2.3.3', mnemonic=WORDS)
        new = self.store.create('new Electron Cash path', mnemonic=WORDS, derivation_path="m/44'/145'/0'")
        self.assertEqual(self.store.get(old['id'])['derivation_coin_type'],1)
        self.assertEqual(self.store.get(new['id'])['derivation_coin_type'],145)
        self.assertEqual(self.store.seed(old['id']),SEED)
        self.assertEqual(self.store.seed(new['id']),SEED)
        self.assertNotEqual(old['address'],new['address'])
        self.assertEqual({w['derivation_path'] for w in self.store.list()},
                         {"m/44'/1'/0'", "m/44'/145'/0'"})
        # Restarting the store must not reassign a prior wallet's path.
        reopened=WalletStore('testnet4',Path(self.tmp.name))
        self.assertEqual(reopened.get(old['id'])['derivation_path'],"m/44'/1'/0'")
        self.assertEqual(reopened.get(new['id'])['derivation_path'],"m/44'/145'/0'")

    def test_signing_uses_same_coin_type_as_receive_and_scan(self):
        addr=address_for(SEED,'testnet4',0,0,0,145)
        dest=address_for(SEED,'testnet4',0,1,0,145)
        utxo={'txid':'ab'*32,'vout':0,'address':addr,'value':400_000,'height':200,
              'branch':0,'idx':0,'tokens':0,'coinbase_immature':False}
        tx=build_signed(SEED,'testnet4',[utxo],dest,120_000,dest,coin_type=145)
        self.assertEqual(parse_tx(tx['raw_hex'])['txid'],tx['txid'])
        with self.assertRaisesRegex(ValueError,'Clave derivada no coincide'):
            build_signed(SEED,'testnet4',[utxo],dest,120_000,dest,coin_type=1)

    def test_expected_public_address_fails_before_writing_secret(self):
        with self.assertRaisesRegex(ValueError,'dirección calculada no coincide'):
            self.store.create('wrong address',mnemonic=WORDS,derivation_path="m/44'/145'/0'",
                              expected_address=address_for(SEED,'testnet4',0,0))
        self.assertEqual(self.store.list(),[])
        self.assertEqual(list(self.store.vault_dir.glob('*.json')),[])

    def test_non_bip44_legacy_key_does_not_take_path(self):
        with self.assertRaisesRegex(ValueError,'clave Legacy no admite ruta HD'):
            self.store.create('bad',legacy_hex='0'*63+'1',derivation_path="m/44'/145'/0'")


if __name__=='__main__':unittest.main()
