"""CashMiner 2.13.1: credit URL uses the default OS browser."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server

ROOT = Path(__file__).resolve().parents[1]
CREDIT_URL = 'https://munia.cash/profile/cashrider'

class CashRiderCreditBrowser2131(unittest.TestCase):
    def test_credit_has_fixed_url_and_no_private_browser_target(self):
        html = (ROOT/'ui/index.html').read_text('utf8')
        self.assertIn('id="cashriderCredit" href="'+CREDIT_URL+'"', html)
        self.assertNotIn('target="_blank"', html)
        self.assertIn("api('/api/external/cashrider',{})", html)
        self.assertIn('event.preventDefault();', html)
        source = (ROOT/'src/cashminer/app/server.py').read_text('utf8')
        self.assertIn("path=='/api/external/cashrider'", source)
        self.assertIn("_open_default_browser('"+CREDIT_URL+"')", source)

    def test_same_default_browser_dispatcher_used_by_explorer(self):
        txid='ab'*32
        with patch.object(server,'_open_default_browser') as dispatch:
            server._open_external_transaction('testnet3',txid)
            dispatch.assert_called_once_with('https://tbch.loping.net/tx/'+txid)

    def test_credit_url_dispatch_through_os_default(self):
        if os.name=='nt':
            with patch.object(server.os,'startfile',create=True) as launch:
                server._open_default_browser(CREDIT_URL)
                launch.assert_called_once_with(CREDIT_URL)
        else:
            with patch.object(server.webbrowser,'open',return_value=True) as launch:
                server._open_default_browser(CREDIT_URL)
                launch.assert_called_once_with(CREDIT_URL,new=2)

if __name__=='__main__':unittest.main()
