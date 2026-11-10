import json
import os
import tempfile
import unittest
from unittest.mock import patch
from cashminer.wallet import legacy_hd as w

class HDWalletTests(unittest.TestCase):
    def test_cashaddr_known_vector(self):
        expected='bchtest:qp63uahgrxged4z5jswyt5dn5v3lzsem6cq85x00dt'
        self.assertEqual(w.address_from_secret(1,'tempnet_fablous_2026'),expected)
        self.assertEqual(w.validate_cashaddr(expected,'tempnet_fablous_2026'),expected)
        with self.assertRaises(ValueError):w.validate_cashaddr(expected[:-1]+'q','tempnet_fablous_2026')
        with self.assertRaises(ValueError):w.validate_cashaddr(expected,'mainnet')

    def test_wallet_encrypt_backup_and_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td}):
                created=w.create_wallet('tempnet_fablous_2026','Mi prueba','Clave más que suficiente 2026')
                self.assertEqual(created['pool_count'],512)
                self.assertTrue(w.verify_password(created['id'],'Clave más que suficiente 2026'))
                with self.assertRaises(ValueError):w.verify_password(created['id'],'incorrecto')
                first,pool=w.mining_destination(created['id'])
                self.assertTrue(first.startswith('bchtest:'))
                with open(pool,encoding='utf-8') as stream: data=stream.read()
                self.assertNotIn('seed_hex',data)
                vault=w.get_wallet(created['id'])
                self.assertNotIn('seed_hex',json.dumps(vault))
                blob=w.export_bundle(created['id'])
                with self.assertRaises(FileExistsError):w.restore_bundle(blob)
                os.remove(os.path.join(td,'wallets','legacy',created['id']+'.wallet.json'))
                os.remove(os.path.join(td,'wallets','legacy',created['id']+'.pool.json'))
                restored=w.restore_bundle(blob)
                self.assertEqual(restored['address'],first)
                self.assertTrue(w.verify_password(created['id'],'Clave más que suficiente 2026'))

if __name__=='__main__':unittest.main()
