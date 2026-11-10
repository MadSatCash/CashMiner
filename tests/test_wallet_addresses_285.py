"""v2.8.5: address listing reads existing SQLite state with pagination only."""
import tempfile
import unittest
from pathlib import Path
from cashminer.wallet.store import WalletStore


class AddressListing285(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WalletStore('testnet3', root=Path(self.temp.name))
        self.wid = 'c' * 32
        with self.store.db() as db:
            db.execute("""INSERT INTO wallets(id,name,first_address,derivation_coin_type,last_sync,tip_height,scan_state,created_at)
                VALUES(?,?,?,1,'2026-11-08T10:00:00Z',1000,'synced','2026-11-08T10:00:00Z')""",
                (self.wid, 'prueba', 'bchtest:first'))
            for branch, count in ((0,65),(1,45)):
                for idx in range(count):
                    db.execute("""INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued,used,status_known)
                        VALUES(?,?,?,?,?,?,?,?)""",
                        (self.wid,branch,idx,f'bchtest:test{branch}-{idx}',f's{branch}-{idx}',int(idx==0),int(idx==0),int(idx!=1)))
            db.executemany("""INSERT INTO utxos(wallet_id,txid,vout,address,value,height,coinbase,tokens)
                VALUES(?,?,?,?,?,?,?,?)""",[
                (self.wid,'a'*64,0,'bchtest:test0-0',100000000,901,1,0),   # mature coinbase
                (self.wid,'b'*64,0,'bchtest:test0-0',200000000,902,1,0),   # immature coinbase
                (self.wid,'c'*64,0,'bchtest:test0-0',300000000,999,0,0),   # normal
                (self.wid,'d'*64,0,'bchtest:test0-0',400000000,999,0,1),   # token locked
                (self.wid,'e'*64,0,'bchtest:test1-0',500000000,1000,0,0),  # change
            ])
    def tearDown(self):
        self.temp.cleanup()

    def test_three_pages_and_stable_order(self):
        first=self.store.address_page(self.wid)
        second=self.store.address_page(self.wid,2)
        third=self.store.address_page(self.wid,3)
        self.assertEqual(first['total'],110)
        self.assertEqual(first['counts'],{'receive':65,'change':45})
        self.assertEqual(first['pages'],3)
        self.assertEqual([len(p['addresses']) for p in (first,second,third)],[50,50,10])
        self.assertEqual(first['addresses'][0]['branch'],0)
        self.assertEqual(first['addresses'][49]['index'],49)
        self.assertEqual(second['addresses'][0]['index'],50)
        self.assertEqual(second['addresses'][15]['branch'],1)
        self.assertEqual(third['addresses'][-1]['index'],44)
        self.assertEqual(len({(a['branch'],a['index']) for p in (first,second,third) for a in p['addresses']}),110)

    def test_balance_maturity_and_token_not_double_counted(self):
        a=self.store.address_page(self.wid)['addresses'][0]
        self.assertEqual(a['total_sats'],1_000_000_000)
        self.assertEqual(a['available_sats'],400_000_000)
        self.assertEqual(a['immature_sats'],200_000_000)
        self.assertEqual(a['token_locked_sats'],400_000_000)
        b=self.store.address_page(self.wid,2)['addresses'][15]
        self.assertEqual(b['branch'],1)
        self.assertEqual(b['available_sats'],500_000_000)
        self.assertTrue(b['used'])

    def test_unknown_address_is_not_labelled_empty(self):
        a=self.store.address_page(self.wid)['addresses'][1]
        self.assertFalse(a['status_known'])
        self.assertIsNone(a['available_sats'])
        self.assertEqual(self.store.address_page(self.wid)['addresses'][2]['total_sats'],0)

    def test_empty_wallet_and_validation(self):
        with self.store.db() as db:
            db.execute('DELETE FROM addresses WHERE wallet_id=?',(self.wid,))
        p=self.store.address_page(self.wid)
        self.assertEqual((p['total'],p['pages'],p['addresses']),(0,1,[]))
        for page in (0,-1,1.5,'2',1_000_001,True):
            with self.subTest(page=page),self.assertRaises(ValueError):
                self.store.address_page(self.wid,page)
        with self.assertRaises(ValueError):self.store.address_page('bad')
        with self.assertRaises(ValueError):self.store.address_page('d'*32)

    def test_no_mutations_or_network_needed(self):
        before=self.store.addresses(self.wid)
        self.store.address_page(self.wid,1)
        self.store.address_page(self.wid,2)
        self.assertEqual(before,self.store.addresses(self.wid))
        # The method uses only WalletStore.db; neither Electrum nor key material is required.
        self.assertFalse((self.store.vault_dir/(self.wid+'.json')).exists())

if __name__=='__main__':unittest.main()
