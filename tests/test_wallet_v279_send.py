"""v2.7.9: HD change lookahead and exact user-entered fee-rate integration."""
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cashminer.wallet.crypto import address_for, decode_address, p2pkh_script, script_hash, sha256d
from cashminer.wallet.store import WalletStore
from cashminer.wallet.transactions import serialize_tx
from cashminer.wallet.sync import scan_wallet
from cashminer.wallet.send import WalletSender

SEED=bytes(range(32))


class OneUtxoElectrum:
    host='electrum.test'; port=50002

    def __init__(self, network, address):
        self.network=network
        self.address=address
        self.sh=script_hash(address,network)
        self.notifications=[]
        raw=serialize_tx([{'txid':'01'*32,'vout':0,'sequence':0xffffffff,'script_sig':b'fund'}],
                         [{'value':1_000_000,'script':p2pkh_script(decode_address(address,network))}])
        self.raw=raw.hex()
        self.txid=sha256d(raw)[::-1].hex()

    def tip_height_hash(self):
        return 1000,'ab'*32

    def rpc(self,method,params):
        if method=='blockchain.transaction.get':
            assert params[0]==self.txid
            return self.raw
        sh=params[0]
        mine=(sh==self.sh)
        if method=='blockchain.scripthash.subscribe':
            return 'ab'*32 if mine else None
        if method=='blockchain.scripthash.get_history':
            return [{'tx_hash':self.txid,'height':500}] if mine else []
        if method=='blockchain.scripthash.listunspent':
            assert params[1]=='include_tokens'
            return [{'tx_hash':self.txid,'tx_pos':0,'height':500,'value':1_000_000}] if mine else []
        raise AssertionError(method)


class Send279(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        protect=patch('cashminer.wallet.store.protect_seed',side_effect=lambda raw,w:b'test|'+raw)
        unprotect=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,w:raw[5:])
        protect.start(); unprotect.start()
        self.addCleanup(protect.stop); self.addCleanup(unprotect.stop)
        self.store=WalletStore('testnet3',Path(tmp.name))
        self.wallet=self.store.create('Sender',recovery_hex=SEED.hex())
        self.destination=address_for(SEED,'testnet3',0,4)
        client=OneUtxoElectrum('testnet3',self.wallet['address'])
        self.assertEqual(scan_wallet(self.store,client,self.wallet['id'],{}),41)

    def test_hd_prepare_after_scan_marks_existing_change_issued_and_advances(self):
        wid=self.wallet['id']
        # Already derived and stored during lookahead. The original v2.7.8
        # INSERT raised UNIQUE constraint failed on this row.
        with self.store.db() as db:
            row=db.execute('SELECT * FROM addresses WHERE wallet_id=? AND branch=1 AND idx=0',(wid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['issued'],0)
        sender=WalletSender()
        first=sender.prepare(self.store,wid,self.destination,'0.001','1,5')
        self.assertEqual(first['amount_sats'],100000)
        tx=sender.previews[first['token']]['tx']
        self.assertEqual(tx['change_address'],address_for(SEED,'testnet3',1,0))
        self.assertGreaterEqual(tx['fee_sats'],int((Decimal('1.5')*tx['byte_size']).to_integral_value(rounding=ROUND_CEILING)))
        self.assertGreater(tx['change_sats'],0)
        self.assertEqual(self.store.get(wid)['change_index'],1)
        second=sender.prepare(self.store,wid,self.destination,'0.001','1.5')
        self.assertEqual(sender.previews[second['token']]['tx']['change_address'],address_for(SEED,'testnet3',1,1))
        self.assertEqual(self.store.get(wid)['change_index'],2)
        with self.store.db() as db:
            rows=db.execute('SELECT idx,issued FROM addresses WHERE wallet_id=? AND branch=1 ORDER BY idx',(wid,)).fetchall()
        self.assertEqual([(r['idx'],r['issued']) for r in rows[:3]],[(0,1),(1,1),(2,0)])

    def test_mismatched_cached_hd_address_fails_without_advancing(self):
        wid=self.wallet['id']
        with self.store.db() as db:
            db.execute('UPDATE addresses SET scripthash=? WHERE wallet_id=? AND branch=1 AND idx=0',('00'*32,wid))
        with self.assertRaisesRegex(ValueError,'incompatible'):
            self.store.issue_change(wid)
        self.assertEqual(self.store.get(wid)['change_index'],0)

    def test_fee_rate_validation(self):
        parse=WalletSender.parse_fee_rate
        self.assertEqual(parse('1'),Decimal(1))
        self.assertEqual(parse('1,5'),Decimal('1.5'))
        self.assertEqual(parse('2.25'),Decimal('2.25'))
        self.assertEqual(parse('0,1'),Decimal('0.1'))
        for invalid in ['0','0,00','-1','+1','nan','Infinity','1,2,3','1e3','1001','',None,True]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                parse(invalid)

    def test_numeric_ui_and_string_wire(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/'ui'/'index.html').read_text('utf8')
        self.assertIn('id="sendFeeRate" type="text" inputmode="decimal"',html)
        self.assertIn('value="1" aria-label="Comisión',html)
        self.assertNotIn('<select class="select" id="sendFeeRate">',html)
        self.assertIn("fee_rate:CMI18n.normalizeInput($('sendFeeRate').value)",html)
        server=(root/'src'/'cashminer'/'app/server.py').read_text('utf8')
        self.assertIn("data.get('fee_rate','1')",server)
        self.assertNotIn("int(data.get('fee_rate'",server)

if __name__=='__main__':unittest.main()
