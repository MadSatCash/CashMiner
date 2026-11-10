"""CashMiner 2.7.10: receive address reuse until a real Electrum movement."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from cashminer.wallet.store import WalletStore
from cashminer.wallet.crypto import address_for

SEED=bytes.fromhex('66'*32)

class Receive2710(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        seed_protect=patch('cashminer.wallet.store.protect_seed', side_effect=lambda data,wid:data+b':'+wid.encode())
        seed_unprotect=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda data,wid:data.split(b':')[0])
        seed_protect.start();seed_unprotect.start()
        self.addCleanup(seed_protect.stop);self.addCleanup(seed_unprotect.stop)
        self.root=Path(self.tmp.name)
        self.store=WalletStore('testnet3',self.root)
        self.wallet=self.store.create('Test',SEED.hex())
        self.wid=self.wallet['id']

    def test_repeated_receive_uses_same_address_even_after_restart(self):
        first=self.store.issue_receive(self.wid)
        self.assertEqual(first['index'],0)
        self.assertEqual(first['address'],address_for(SEED,'testnet3',0,0))
        for _ in range(8):
            nxt=self.store.issue_receive(self.wid)
            self.assertEqual(nxt['address'],first['address'])
            self.assertTrue(nxt['reused'])
        other=WalletStore('testnet3',self.root)
        self.assertEqual(other.issue_receive(self.wid)['index'],0)
        self.assertEqual(other.get(self.wid)['receive_index'],1)

    def test_move_to_next_only_when_used_and_do_not_reuse_spent(self):
        first=self.store.issue_receive(self.wid)
        with self.store.db() as db:
            db.execute('UPDATE addresses SET used=1 WHERE wallet_id=? AND branch=0 AND idx=0',(self.wid,))
        second=self.store.issue_receive(self.wid)
        self.assertEqual(second['index'],1)
        self.assertNotEqual(second['address'],first['address'])
        self.assertEqual(self.store.issue_receive(self.wid)['index'],1)
        with self.store.db() as db:
            db.execute('UPDATE addresses SET used=1 WHERE wallet_id=? AND branch=0 AND idx=1',(self.wid,))
        self.assertEqual(self.store.issue_receive(self.wid)['index'],2)
        self.assertEqual(self.store.get(self.wid)['receive_index'],3)

    def test_legacy_old_issued_indices_still_monitored_but_no_longer_advance(self):
        # Simulates 2.7.9 repeatedly showing unused addresses 0..5.
        for idx in range(6):
            addr=address_for(SEED,'testnet3',0,idx)
            from cashminer.wallet.crypto import script_hash
            with self.store.db() as db:
                db.execute('INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued) VALUES(?,?,?,?,?,1)',
                           (self.wid,0,idx,addr,script_hash(addr,'testnet3')))
        with self.store.db() as db:
            db.execute('UPDATE wallets SET receive_index=6 WHERE id=?',(self.wid,))
        self.assertEqual(self.store.issue_receive(self.wid)['index'],0)
        self.assertEqual(self.store.get(self.wid)['receive_index'],6)
        self.assertEqual(len(self.store.addresses(self.wid)),6)
        with self.store.db() as db:
            db.execute('UPDATE addresses SET used=1 WHERE wallet_id=? AND branch=0 AND idx=0',(self.wid,))
        self.assertEqual(self.store.issue_receive(self.wid)['index'],1)
        self.assertEqual(self.store.get(self.wid)['receive_index'],6)

    def test_corrupt_existing_address_is_not_overwritten(self):
        self.store.issue_receive(self.wid)
        with self.store.db() as db:
            db.execute('UPDATE addresses SET scripthash=? WHERE wallet_id=? AND branch=0 AND idx=0',('bad',self.wid))
        with self.assertRaisesRegex(ValueError,'no coincide'):
            self.store.issue_receive(self.wid)

    def test_qr_is_local_and_no_reservation_warning(self):
        html=(Path(__file__).resolve().parents[1]/'ui'/'index.html').read_text('utf-8')
        self.assertIn('src="/assets/qrcode.min.js"',html)
        self.assertIn("new QRCode($('walletReceiveQr')",html)
        self.assertIn('text:address',html)
        self.assertIn('wallet-receive-inline',html)
        self.assertNotIn('Esta dirección queda reservada',html)
        self.assertTrue((Path(__file__).resolve().parents[1]/'ui/vendor/qrcode.min.js').is_file())

if __name__=='__main__':unittest.main()
