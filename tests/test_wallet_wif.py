"""Public private-key vectors only; temporary stores, no live wallet/network."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cashminer.wallet.crypto import ORDER, PREFIX, address_for_legacy, decode_wif
from cashminer.wallet.store import WalletStore

# Public secp256k1 scalar 1 vectors; never fund these addresses.
COMPRESSED = 'KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rFU73sVHnoWn'
UNCOMPRESSED = '5HpHagT65TZzG1PH3CSu63k8DbpvD8s5ip4nEB3kEsreAnchuDf'


def encode_test_wif(scalar=1, prefix=0x80, suffix=b'\x01', extra=b''):
    """Independent encoder for malformed inputs and boundary vectors."""
    payload = bytes([prefix]) + scalar.to_bytes(32, 'big') + suffix + extra
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(payload + checksum, 'big')
    encoded = ''
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return encoded


class WifDecoding(unittest.TestCase):
    def test_known_mainnet_vectors(self):
        self.assertEqual(decode_wif(COMPRESSED, 'mainnet'), (1, True))
        self.assertEqual(decode_wif(' \n'+UNCOMPRESSED+'\n', 'mainnet'), (1, False))
        self.assertEqual(encode_test_wif(), COMPRESSED)
        self.assertEqual(encode_test_wif(suffix=b''), UNCOMPRESSED)

    def test_network_prefix_and_test_chain_ambiguity(self):
        for network in PREFIX:
            if network == 'mainnet':
                continue
            for compressed in (True, False):
                wif = encode_test_wif(prefix=0xef, suffix=b'\x01' if compressed else b'')
                self.assertEqual(decode_wif(wif, network), (1, compressed))
                with self.assertRaisesRegex(ValueError, 'otra red'):
                    decode_wif(COMPRESSED, network)
                with self.assertRaisesRegex(ValueError, 'otra red'):
                    decode_wif(wif, 'mainnet')

    def test_rejects_corruption_and_invalid_characters(self):
        for wif in (None, '', '0'*52, COMPRESSED[:-1]+'0', COMPRESSED[:-1]+'o',
                    COMPRESSED[:20]+' '+COMPRESSED[21:], COMPRESSED+'1', COMPRESSED[:-2]):
            with self.subTest(value_type=type(wif).__name__), self.assertRaises(ValueError):
                decode_wif(wif, 'mainnet')
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            decode_wif(COMPRESSED[:-1]+'m', 'mainnet')

    def test_rejects_bad_payload_even_with_valid_checksum(self):
        for kwargs in ({'scalar': 0}, {'scalar': ORDER}, {'scalar': 2**256-1},
                       {'suffix': b'\x02'}, {'prefix': 0x81}, {'extra': b'\x01'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                decode_wif(encode_test_wif(**kwargs), 'mainnet')
        self.assertEqual(decode_wif(encode_test_wif(ORDER-1), 'mainnet'), (ORDER-1, True))


class WifImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for mock in (patch('cashminer.wallet.store.protect_seed', side_effect=lambda s,w: b'test|'+s),
                     patch('cashminer.wallet.store.unprotect_seed', side_effect=lambda s,w: s.split(b'|',1)[1])):
            mock.start()
            self.addCleanup(mock.stop)

    def test_equivalent_hex_wif_addresses_and_recovery(self):
        for network in PREFIX:
            for compressed in (True, False):
                with self.subTest(network=network, compressed=compressed):
                    store = WalletStore(network, Path(self.tmp.name)/str(compressed))
                    wif = encode_test_wif(prefix=0x80 if network=='mainnet' else 0xef,
                                          suffix=b'\x01' if compressed else b'')
                    candidates = store.legacy_candidates(private_wif=wif)
                    expected = address_for_legacy(1, network, compressed)
                    self.assertEqual(candidates, [dict(address=expected, compressed=compressed,
                                      label='Comprimida' if compressed else 'Sin comprimir')])
                    # An API caller cannot override the embedded compression flag.
                    wallet = store.create('WIF vector', private_wif=wif,
                                          legacy_compressed=not compressed, expected_address=expected)
                    self.assertEqual(wallet['address'], expected)
                    self.assertEqual(wallet['wallet_type'], 'legacy-compressed' if compressed else 'legacy-uncompressed')
                    self.assertEqual(store.issue_receive(wallet['id'])['address'], expected)
                    self.assertEqual(store.recovery(wallet['id'])['private_key_hex'], '0'*63+'1')
                    with self.assertRaisesRegex(ValueError, 'ya existe'):
                        store.create('Equivalent hex', legacy_hex='0'*63+'1',
                                     legacy_compressed=compressed, expected_address=expected)
                    self.assertNotIn(wif, json.dumps(wallet))
                    self.assertNotIn(wif, store.path.read_bytes().decode('latin1'))

    def test_confirmation_and_format_conflicts_do_not_write_wallets(self):
        store = WalletStore('mainnet', Path(self.tmp.name))
        for kwargs in ({}, {'expected_address': 'bitcoincash:wrong'},
                       {'legacy_hex': '0'*63+'1'}, {'recovery_hex': '00'*32},
                       {'mnemonic': 'abandon '*11+'about'}, {'derivation_path': "m/44'/145'/0'"}):
            with self.subTest(fields=list(kwargs)), self.assertRaises(ValueError):
                store.create('Invalid', private_wif=COMPRESSED, **kwargs)
        with self.assertRaises(ValueError):
            store.legacy_candidates('0'*63+'1', private_wif=COMPRESSED)
        self.assertEqual(store.list(), [])
        self.assertEqual(list(store.vault_dir.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
