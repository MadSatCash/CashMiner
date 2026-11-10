"""v2.7.12: one broadcast attempt, truthful outcomes, safe logs and no hidden retries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sqlite3

from cashminer.wallet.send import WalletSender
from cashminer.wallet.electrum import ElectrumError, ElectrumRPCError
from cashminer.wallet.store import WalletStore
from cashminer.wallet.crypto import address_for_legacy


class SendOutcomes2711(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        p=patch('cashminer.wallet.store.protect_seed',side_effect=lambda raw,w:b'test|'+raw)
        u=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,w:raw[5:])
        p.start();u.start();self.addCleanup(p.stop);self.addCleanup(u.stop)
        self.store=WalletStore('testnet3',Path(tmp.name))
        self.wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',expected_address=address_for_legacy(1,'testnet3',True))
        # We only need the public send outcome; don't construct a real spend.
        self.sender=WalletSender()
        self.txid='ab'*32
        self.tx={'txid':self.txid,'raw_hex':'01000000','amount_sats':100000,
                 'destination':address_for_legacy(2,'testnet3',True),'fee_sats':200,
                 'input_refs':[], 'change_address':self.wallet['address']}
        self.token='one-time-token'
        self.sender.previews[self.token]={'deadline':10**20,'wid':self.wallet['id'],
            'network':'testnet3','tx':self.tx}
        with self.store.db() as db:
            db.execute('UPDATE wallets SET provider=? WHERE id=?',
                       ('testnet.imaginary.cash:50002',self.wallet['id']))
        self.store.mark_error(self.wallet['id'],'test initial')

    def _invoke(self, reply):
        with patch.object(self.sender,'_broadcast_to_server',side_effect=reply if isinstance(reply,Exception) else None,
                          return_value=reply if not isinstance(reply,Exception) else None) as rpc:
            out=self.sender.broadcast(self.store,self.wallet['id'],self.token)
            self.assertEqual(rpc.call_count,1)
        self.assertEqual(out['txid'],self.txid)
        self.assertEqual(out['amount_sats'],100000)
        self.assertEqual(out['fee_sats'],200)
        with self.store.db() as db:
            rec=dict(db.execute('SELECT * FROM local_transactions WHERE txid=?',(self.txid,)).fetchone())
        self.assertEqual(rec['raw_hex'],'')
        self.assertNotIn(self.token,self.sender.previews)
        with patch.object(self.sender,'_broadcast_to_server') as again:
            with self.assertRaisesRegex(ValueError,'venció'):
                self.sender.broadcast(self.store,self.wallet['id'],self.token)
            again.assert_not_called()
        return out,rec

    def test_exact_txid_is_success(self):
        out,rec=self._invoke(self.txid)
        self.assertEqual(out['status'],'sent')
        self.assertEqual(rec['state'],'broadcast')

    def test_server_txid_mismatch_is_uncertain_not_failure(self):
        out,rec=self._invoke('cd'*32)
        self.assertEqual(out['status'],'uncertain')
        self.assertEqual(rec['state'],'uncertain')

    def test_server_response_type_mismatch_is_uncertain(self):
        out,rec=self._invoke({'txid':self.txid})
        self.assertEqual(out['status'],'uncertain')
        self.assertEqual(rec['state'],'uncertain')

    def test_explicit_rpc_rejection(self):
        out,rec=self._invoke(ElectrumRPCError('blockchain.transaction.broadcast',{'code':-26,'message':'missing inputs'}))
        self.assertEqual(out['status'],'rejected')
        self.assertIn('missing inputs',out['message'])
        self.assertEqual(rec['state'],'rejected')

    def test_transport_disconnect_is_uncertain(self):
        out,rec=self._invoke(ElectrumError('Servidor Electrum desconectado'))
        self.assertEqual(out['status'],'uncertain')
        self.assertEqual(rec['state'],'uncertain')

    def test_interface_is_not_a_retry_screen(self):
        html=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text('utf8')
        self.assertIn('function showSendResult(',html)
        self.assertIn('id="copyBroadcastTxid"',html)
        self.assertIn("https://bchexplorer.cash/tx/",html)
        self.assertIn("https://tbch.loping.net/tx/",html)
        self.assertIn('id="sendResultDone"',html)
        self.assertNotIn('Dirección de recepción #',html)
        self.assertIn('.wallet-receive-address{width:100%',html)
        self.assertNotIn('id="sendRetry"',html)

if __name__=='__main__':unittest.main()
