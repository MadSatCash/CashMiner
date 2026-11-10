"""v2.7.10: BIP39 entropy selection, recovery roundtrips, UI wiring."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.wallet.bip39 import mnemonic_to_entropy, mnemonic_to_seed
from cashminer.wallet.crypto import address_for
from cashminer.wallet.store import WalletStore

ROOT = Path(__file__).resolve().parents[1]

class NewBip39Wallets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        # Test only: never encrypt production secrets using this mock.
        p1=patch('cashminer.wallet.store.protect_seed', side_effect=lambda raw,wid:b'TEST:'+raw)
        p2=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,wid:raw[5:])
        p1.start();p2.start();self.addCleanup(p1.stop);self.addCleanup(p2.stop)
        self.store=WalletStore('testnet3',Path(self.tmp.name))

    def test_default_is_12_words_and_recoverable(self):
        wallet=self.store.create('default')
        phrase=wallet['recovery_phrase']
        self.assertEqual(len(phrase.split()),12)
        self.assertEqual(len(mnemonic_to_entropy(phrase)),16)
        self.assertEqual(self.store.recovery(wallet['id'])['mnemonic'],phrase)
        self.assertEqual(wallet['address'],address_for(mnemonic_to_seed(phrase),'testnet3',0,0))

    def test_all_supported_lengths_survive_reopen_and_restore(self):
        for count in (12,15,18,21,24):
            with self.subTest(words=count):
                wallet=self.store.create('words '+str(count),bip39_words=count)
                phrase=wallet['recovery_phrase']
                self.assertEqual(len(phrase.split()),count)
                self.assertEqual(len(mnemonic_to_entropy(phrase)),count*4//3)
                self.assertEqual(self.store.recovery(wallet['id'])['mnemonic'],phrase)
                self.assertEqual(self.store.seed(wallet['id']),mnemonic_to_seed(phrase))
                self.assertEqual(wallet['address'],address_for(mnemonic_to_seed(phrase),'testnet3',0,0))
                reopened=WalletStore('testnet3',Path(self.tmp.name))
                self.assertEqual(reopened.recovery(wallet['id'])['mnemonic'],phrase)
                self.assertEqual(reopened.get(wallet['id'])['first_address'],wallet['address'])

    def test_invalid_count_fails_before_writing_secrets(self):
        for count in (0,11,13,16,23,25,32,'12',12.0,True,None):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError,'BIP39 requiere'):
                    self.store.create('invalid',bip39_words=count)
        self.assertEqual(self.store.list(),[])

    def test_bip32_and_legacy_unchanged(self):
        wallet=self.store.create('bip32',new_type='raw-bip32',seed_bytes=64)
        self.assertEqual(len(self.store.recovery(wallet['id'])['seed_hex']),128)
        legacy=self.store.create('legacy',new_type='legacy-hex')
        self.assertEqual(len(self.store.recovery(legacy['id'])['private_key_hex']),64)

    def test_ui_hides_irrelevant_option_and_sends_selected_word_count(self):
        html=(ROOT/'ui/index.html').read_text('utf8')
        for count in (12,15,18,21,24):
            self.assertIn(f'name="newWalletBip39Words" value="{count}"',html)
        self.assertIn('name="newWalletBip39Words" value="12" checked',html)
        self.assertIn('id="newWalletBip32Field"',html)
        self.assertIn("type!=='bip39'",html)
        self.assertIn("type!=='raw-bip32'",html)
        self.assertIn('options.bip39_words=',html)
        self.assertIn("options.seed_bytes=",html)
        self.assertIn('CashMiner v2.11',html)

    def test_http_endpoint_passes_word_count_to_store(self):
        server=(ROOT/'src/cashminer/app/server.py').read_text('utf8')
        self.assertIn("bip39_words=data.get('bip39_words',12)",server)

if __name__=='__main__':unittest.main()
