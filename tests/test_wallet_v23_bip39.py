"""Offline BIP39 and multiwallet regression tests. No real wallet secrets or network."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.wallet.bip39 import (
    entropy_to_mnemonic, mnemonic_to_entropy, mnemonic_to_seed,
)
from cashminer.wallet.crypto import address_for
from cashminer.wallet.store import WalletStore

ZERO_12 = 'abandon ' * 11 + 'about'
ZERO_24 = 'abandon ' * 23 + 'art'


class Bip39Vectors(unittest.TestCase):
    def test_bip39_128bit_vector_and_seed(self):
        self.assertEqual(entropy_to_mnemonic(bytes(16)), ZERO_12)
        self.assertEqual(mnemonic_to_entropy(ZERO_12), bytes(16))
        self.assertEqual(mnemonic_to_seed(ZERO_12, 'TREZOR').hex(),
                         'c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553'
                         '1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04')
    def test_bip39_256bit_vector_and_checksums(self):
        self.assertEqual(entropy_to_mnemonic(bytes(32)), ZERO_24)
        self.assertEqual(mnemonic_to_entropy(ZERO_24), bytes(32))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            mnemonic_to_entropy(ZERO_12.replace('about', 'abandon'))
        with self.assertRaises(ValueError):
            mnemonic_to_entropy('abandon ' * 11 + 'invalidword')
        self.assertEqual(len(mnemonic_to_seed(ZERO_24)), 64)


class WalletRoundTrip(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Simulates Windows encryption for deterministic Linux CI. This patch
        # is only in tests; production refuses to store plaintext on Linux.
        self.a = patch('cashminer.wallet.store.protect_seed',
                       side_effect=lambda secret, wallet_id: b'test-enc:' + secret)
        self.b = patch('cashminer.wallet.store.unprotect_seed',
                       side_effect=lambda blob, wallet_id: blob.removeprefix(b'test-enc:'))
        self.a.start(); self.b.start()
        self.addCleanup(self.a.stop); self.addCleanup(self.b.stop)
        self.store = WalletStore('testnet4', Path(self.temp.name))

    def test_restore_12_words_and_network_separation(self):
        created = self.store.create('test 12', mnemonic=ZERO_12)
        self.assertEqual(self.store.recovery(created['id'])['mnemonic'], ZERO_12)
        seed = mnemonic_to_seed(ZERO_12)
        self.assertEqual(self.store.seed(created['id']), seed)
        self.assertEqual(created['address'], address_for(seed, 'testnet4', 0, 0))
        self.assertEqual(WalletStore('mainnet', Path(self.temp.name)).list(), [])
        with self.assertRaisesRegex(ValueError, 'existe'):
            self.store.create('duplicada', mnemonic=ZERO_12)

    def test_create_24_words_portable_and_existing_bip32(self):
        created = self.store.create('new', bip39_words=24)
        words = created['recovery_phrase']
        self.assertEqual(len(words.split()), 24)
        self.assertEqual(len(mnemonic_to_entropy(words)), 32)
        self.assertEqual(self.store.recovery(created['id'])['mnemonic'], words)
        self.assertEqual(self.store.seed(created['id']), mnemonic_to_seed(words))
        old = self.store.create('legacy', recovery_hex=bytes(range(32)).hex())
        self.assertEqual(self.store.recovery(old['id'])['kind'], 'raw-bip32')
        self.assertEqual(self.store.seed(old['id']), bytes(range(32)))

    def test_internal_transfer_updates_sender_change_and_receiver(self):
        sender = self.store.create('sender', recovery_hex=bytes(range(32)).hex())
        recipient = self.store.create('recipient', recovery_hex=bytes(range(1,33)).hex())
        receiver_address = self.store.issue_receive(recipient['id'])['address']
        change = self.store.issue_change(sender['id'])['address']
        source_address = sender['address']
        self.store.apply_snapshot(sender['id'],
            [{'branch':0,'idx':0,'address':source_address,'scripthash':'x','issued':1,'used':1}],
            [{'txid':'aa'*32,'vout':0,'address':source_address,'value':500000,
              'height':180,'coinbase':0,'tokens':0}], [], 300, 'b'*64, 'test:50002')
        self.store.apply_snapshot(recipient['id'], [], [], [], 300, 'b'*64, 'test:50002')
        tx = {'txid':'11'*32, 'input_refs':[('aa'*32,0)], 'input_addresses':[source_address], 'destination':receiver_address,
              'amount_sats':100000, 'change_sats':399400, 'change_address':change,
              'raw_hex':'0001'}
        affected = self.store.note_broadcast(sender['id'], tx)
        self.assertIn(recipient['id'], affected)
        balances = {w['id']:w for w in self.store.list()}
        # Only the accepted sender's own spent inputs and change are projected.
        self.assertEqual(balances[sender['id']]['total_sats'], 399400)
        self.assertEqual(balances[sender['id']]['available_sats'], 399400)
        self.assertEqual(balances[recipient['id']]['total_sats'], 0)
        self.assertEqual(balances[recipient['id']]['unconfirmed_sats'], 0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending_spends').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM local_transactions').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
