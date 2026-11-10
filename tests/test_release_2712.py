"""Regression checks for the specific 2.7.12 fixes, without live broadcasts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cashminer.wallet.send import WalletSender
from cashminer.wallet.store import WalletStore
from cashminer.wallet.crypto import address_for_legacy
from cashminer.app import server as app_server

ROOT=Path(__file__).resolve().parents[1]
SUCCESS_HTML='<br/><br/>Your transaction was successfully broadcast.<br/><br/>However, you are using a VULNERABLE version of Electron Cash.<br/>Download the latest version from this web site ONLY:<br/>https://electroncash.org/<br/><br/>'


class OldElectrumNotice(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        a=patch('cashminer.wallet.store.protect_seed',side_effect=lambda raw,w:b'test|'+raw)
        b=patch('cashminer.wallet.store.unprotect_seed',side_effect=lambda raw,w:raw[5:])
        a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
        self.store=WalletStore('testnet3',Path(tmp.name))
        self.wallet=self.store.create('Legacy',legacy_hex='0'*63+'1',expected_address=address_for_legacy(1,'testnet3',True))
        self.sender=WalletSender()
        self.txid='ab'*32
        self.tx={'txid':self.txid,'raw_hex':'01000000','amount_sats':100000,'destination':address_for_legacy(2,'testnet3',True),
                 'fee_sats':200,'input_refs':[],'change_address':self.wallet['address']}
        with self.store.db() as db:
            db.execute('UPDATE wallets SET provider=? WHERE id=?',('testnet.imaginary.cash:50002',self.wallet['id']))
        self.store.mark_error(self.wallet['id'],'test setup')

    def send(self,reply):
        token='single-use'
        self.sender.previews[token]={'deadline':10**20,'wid':self.wallet['id'],'network':'testnet3','tx':self.tx}
        with patch.object(self.sender,'_broadcast_to_server',return_value=reply) as rpc:
            out=self.sender.broadcast(self.store,self.wallet['id'],token)
            rpc.assert_called_once()
        return out

    def test_real_2026_11_08_log_response_is_success(self):
        out=self.send(SUCCESS_HTML)
        self.assertEqual(out['status'],'sent')
        self.assertEqual(out['txid'],self.txid)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM local_transactions WHERE txid=?',(self.txid,)).fetchone()[0],'broadcast')

    def test_unknown_response_stays_uncertain(self):
        for response in ('Your transaction failed successfully.', 'ERROR: Your transaction was successfully broadcast.',
                         'bad TXID', {'result':SUCCESS_HTML},'cd'*32):
            with self.subTest(response=response):
                self.assertFalse(WalletSender._legacy_broadcast_ack(response))
        out=self.send('cd'*32)
        self.assertEqual(out['status'],'uncertain')

    def test_only_initial_explicit_success_sentence_counts(self):
        self.assertTrue(WalletSender._legacy_broadcast_ack(SUCCESS_HTML))
        self.assertTrue(WalletSender._legacy_broadcast_ack('Your transaction was successfully broadcast.'))
        self.assertFalse(WalletSender._legacy_broadcast_ack('A warning!\nYour transaction was successfully broadcast.'))
        self.assertFalse(WalletSender._legacy_broadcast_ack('<b>Your transaction was successfully broadcast.</b>'))
        self.assertFalse(WalletSender._legacy_broadcast_ack('Your transaction was successfully broadcast!' ))
        self.assertFalse(WalletSender._legacy_broadcast_ack('Your transaction was successfully broadcast.'+'!'*5000))


class ExternalBrowser2712(unittest.TestCase):
    def test_only_allowed_explorers(self):
        txid='ff'*32
        self.assertEqual(app_server._transaction_explorer_url('mainnet',txid),'https://bchexplorer.cash/tx/'+txid)
        self.assertEqual(app_server._transaction_explorer_url('testnet3',txid),'https://tbch.loping.net/tx/'+txid)
        self.assertEqual(app_server._transaction_explorer_url('testnet4',txid),'https://tbch4.loping.net/tx/'+txid)
        for network, bad in [('unknown',txid),('mainnet','../../foo'),('mainnet','123'),('testnet3','https://evil.example')]:
            with self.subTest(network=network,bad=bad):
                with self.assertRaises(ValueError):app_server._transaction_explorer_url(network,bad)

    def test_default_browser_open_not_private_browser(self):
        txid='ac'*32
        with patch.object(app_server.webbrowser,'open',return_value=True) as open_browser:
            app_server._open_external_transaction('testnet3',txid)
            if os.name!='nt':open_browser.assert_called_once_with('https://tbch.loping.net/tx/'+txid,new=2)

    def test_browser_order_when_brave_is_default(self):
        with patch.object(app_server,'_default_chromium_name',return_value='brave'):
            with patch.dict(os.environ,{'PROGRAMFILES':'C:/Program Files','PROGRAMFILES(X86)':'C:/Program Files (x86)','LOCALAPPDATA':'C:/Users/foo/AppData/Local'},clear=False):
                with patch.dict(os.environ,{'CASHMINER2_BROWSER_EXE':''}):
                    candidates=app_server._browser_candidates()
        self.assertIn('BraveSoftware',str(candidates[0]))
        self.assertIn('Microsoft', '\n'.join(map(str,candidates)))
        self.assertIn('Google', '\n'.join(map(str,candidates)))

    def test_browser_order_when_edge_default(self):
        with patch.object(app_server,'_default_chromium_name',return_value='edge'):
            with patch.dict(os.environ,{'PROGRAMFILES':'C:/Program Files','LOCALAPPDATA':''},clear=False):
                with patch.dict(os.environ,{'CASHMINER2_BROWSER_EXE':''}):
                    candidates=app_server._browser_candidates()
        self.assertIn('Microsoft',str(candidates[0]))

    def test_ui_routes_links_and_centered_copy(self):
        html=(ROOT/'ui/index.html').read_text(encoding='utf8')
        self.assertIn('id="walletReceiveAddress"',html)
        self.assertNotIn('id="copyReceive"',html)
        self.assertIn("api('/api/external/transaction',{network,txid})",html)
        self.assertIn("api('/api/external/cashrider',{})",html)
        self.assertIn('id="cashriderCredit"',html)
        self.assertIn('event.preventDefault();',html)
        self.assertNotIn('target="_blank"',html)
        self.assertIn('id="copyBroadcastTxid"',html)
        server=(ROOT/'src/cashminer/app/server.py').read_text(encoding='utf8')
        self.assertIn("path=='/api/external/transaction'",server)
        self.assertIn("path=='/api/external/cashrider'",server)
        self.assertIn("_open_default_browser('https://munia.cash/profile/cashrider')",server)
        self.assertIn('os.startfile(url)',server)
        self.assertNotIn('Navegador de interfaz:',server)


if __name__=='__main__':unittest.main()
