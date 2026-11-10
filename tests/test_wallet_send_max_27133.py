"""Send-MAX safety regressions: offline Testnet3, no private user data or RPC."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import unittest
from unittest.mock import Mock
from cashminer.wallet.crypto import address_for_legacy, address_for
from cashminer.wallet.send import WalletSender
from cashminer.wallet.transactions import (MAX_STANDARD_TX_SIZE, build_signed, parse_tx,
                                      serialize_tx, varint, DUST)

DEST=address_for_legacy(2,'testnet3',True)
SOURCE=address_for_legacy(1,'testnet3',True)

def utxos(n,value=10000,address=SOURCE):
    return [dict(txid=f'{i+1:064x}',vout=0,value=value,address=address,
                 height=500,coinbase=False,tokens=0,branch=0,idx=0) for i in range(n)]

def sign(items, amount=None, *, send_max=True, fee_rate=1):
    return build_signed(None,'testnet3',items,DEST,amount,SOURCE,fee_rate,
                        legacy_private=1,legacy_compressed=True,send_max=send_max)

class Max27133(unittest.TestCase):
    def test_single_output_no_change_and_exact_signed_fee_floor(self):
        items=utxos(3,100_000)
        tx=sign(items,fee_rate=Decimal('1.5'))
        parsed=parse_tx(tx['raw_hex'])
        self.assertEqual(len(parsed['inputs']),3)
        self.assertEqual(len(parsed['outputs']),1)
        self.assertEqual(tx['change_sats'],0)
        self.assertIsNone(tx['change_address'])
        self.assertEqual(tx['amount_sats']+tx['fee_sats'],300_000)
        self.assertEqual(parsed['outputs'][0]['value'],tx['amount_sats'])
        self.assertGreaterEqual(tx['fee_sats'],int((Decimal('1.5')*tx['byte_size']).to_integral_value(rounding=ROUND_CEILING)))
        self.assertLessEqual(tx['fee_sats'],int((Decimal('1.5')*(tx['byte_size']+4)).to_integral_value(rounding=ROUND_CEILING)))
        self.assertEqual(tx['send_max'],True)

    def test_unprofitable_inputs_remain_unspent(self):
        items=utxos(2,100_000)+[dict(txid='bb'*32,vout=0,value=20,address=SOURCE,
                          height=500,coinbase=False,tokens=0,branch=0,idx=0)]
        tx=sign(items)
        self.assertEqual(tx['inputs'],2)
        self.assertEqual(tx['skipped_count'],1)
        self.assertEqual(tx['skipped_sats'],20)
        self.assertEqual(tx['amount_sats']+tx['fee_sats'],200_000)

    def test_immature_and_token_inputs_not_selected(self):
        items=utxos(1,100_000)
        items+=[dict(utxos(1,999_999)[0],txid='ab'*32,coinbase=True,height=0),
                dict(utxos(1,999_999)[0],txid='cd'*32,tokens=1)]
        tx=sign(items)
        self.assertEqual(tx['inputs'],1)
        self.assertEqual(tx['amount_sats']+tx['fee_sats'],100_000)

    def test_more_than_sixty_inputs_both_modes(self):
        items=utxos(80,10_000)
        tx=sign(items)
        self.assertEqual(tx['inputs'],80)
        ordinary=sign(items,680_000,send_max=False)
        self.assertGreater(ordinary['inputs'],60)
        self.assertLessEqual(ordinary['byte_size'],MAX_STANDARD_TX_SIZE)
        self.assertGreaterEqual(ordinary['change_sats'],0)

    def test_compactsize_boundary_252_253_signed(self):
        self.assertEqual(varint(252),b'\xfc')
        self.assertEqual(varint(253),b'\xfd\xfd\x00')
        tx=sign(utxos(253,10_000))
        parsed=parse_tx(tx['raw_hex'])
        self.assertEqual(tx['inputs'],253)
        self.assertEqual(len(parsed['inputs']),253)
        self.assertEqual(tx['amount_sats']+tx['fee_sats'],2_530_000)
        self.assertEqual(len(parsed['outputs']),1)

    def test_over_standard_size_fails_before_signing_no_partial_max(self):
        with self.assertRaisesRegex(ValueError,'100.000 bytes'):
            sign(utxos(800,10_000))

    def test_fee_too_high_for_funds_fails(self):
        with self.assertRaisesRegex(ValueError,'no cubre|rentables'):
            sign(utxos(1,1000),fee_rate=10)

    def test_max_cannot_accept_manual_amount(self):
        with self.assertRaisesRegex(ValueError,'importe manual'):
            sign(utxos(1),amount=1_000)

    def test_sender_hd_max_does_not_allocate_change_address(self):
        seed=bytes(range(32));src=address_for(seed,'testnet3',0,0,coin_type=1)
        stub=Mock()
        stub.network='testnet3'
        stub.get.return_value={'wallet_type':'bip39','last_sync':datetime.now(timezone.utc).isoformat(),
                               'scan_state':'synced','tip_height':1000,'tip_hash':'ab'*32,
                               'account_index':0,'derivation_coin_type':1}
        stub.spending_utxos.return_value=utxos(2,100_000,src)
        stub.seed.return_value=seed
        sender=WalletSender()
        result=sender.prepare(stub,'w',DEST,'','1',True)
        tx=sender.previews[result['token']]['tx']
        self.assertEqual(result['send_max'],True)
        self.assertEqual(result['amount_sats'],tx['amount_sats'])
        self.assertEqual(tx['change_sats'],0)
        stub.issue_change.assert_not_called()

    def test_max_broadcast_updates_local_wallet_without_change(self):
        import tempfile
        from unittest.mock import patch
        from cashminer.wallet.store import WalletStore
        from cashminer.wallet.sync import scan_wallet
        from cashminer.wallet.crypto import (script_hash,decode_address,p2pkh_script,sha256d)
        class ElectrumOffline:
            host='fake.local';port=50002;notifications=[]
            def __init__(self,addr):
                self.addr=addr
                raw=serialize_tx([{'txid':'fe'*32,'vout':0,'sequence':0xffffffff,'script_sig':b'fund'}],
                                 [{'value':2_000_000,'script':p2pkh_script(decode_address(addr,'testnet3'))}])
                self.raw=raw.hex();self.txid=sha256d(raw)[::-1].hex()
            def tip_height_hash(self):return 1000,'ab'*32
            def rpc(self,method,params):
                if method=='blockchain.transaction.get':return self.raw
                mine=params[0]==script_hash(self.addr,'testnet3')
                if method=='blockchain.scripthash.subscribe':return 'aa'*32 if mine else None
                if method=='blockchain.scripthash.get_history':return [{'tx_hash':self.txid,'height':500}] if mine else []
                if method=='blockchain.scripthash.listunspent':
                    return [{'tx_hash':self.txid,'tx_pos':0,'height':500,'value':2_000_000}] if mine else []
                raise AssertionError(method)
        with tempfile.TemporaryDirectory() as tmp, \
             patch('cashminer.wallet.store.protect_seed',side_effect=lambda x,w:b'noop'+x), \
             patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda x,w:x[4:]):
            store=WalletStore('testnet3',Path(tmp))
            w=store.create('Legacy',legacy_hex='0'*63+'1',expected_address=SOURCE)
            client=ElectrumOffline(w['address'])
            scan_wallet(store,client,w['id'],{})
            sender=WalletSender()
            preview=sender.prepare(store,w['id'],DEST,'','1',True)
            tx=sender.previews[preview['token']]['tx']
            self.assertEqual(len(parse_tx(tx['raw_hex'])['outputs']),1)
            with patch.object(sender,'_broadcast_to_server',return_value=preview['txid']):
                result=sender.broadcast(store,w['id'],preview['token'])
            self.assertEqual(result['status'],'sent')
            self.assertEqual(store.get(w['id'])['scan_state'],'synced')
            self.assertEqual(store.list()[0]['available_sats'],0)
            self.assertEqual(store.utxos(w['id']),[])
            self.assertEqual(tx['amount_sats']+tx['fee_sats'],2_000_000)

    def test_ui_wires_max_mode_to_api_and_confirmation(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/'ui/index.html').read_text(encoding='utf8')
        server=(root/'src/cashminer/app/server.py').read_text(encoding='utf8')
        self.assertIn('id="sendMax"',html)
        self.assertIn('send_max:sendMaxMode',html)
        self.assertIn('Enviar todo (MAX)',html)
        self.assertIn("data.get('send_max',False)",server)
        self.assertNotIn('mining-card-event" data-kind',html)
        self.assertIn('seenMinerEvents',html)
        self.assertIn('},900)',html)

if __name__=='__main__':unittest.main()
