"""Presentation-only i18n and locale-safe satoshi formats for v2.10."""
import unittest
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch
import tempfile, os, threading
from cashminer.app import server as app_server

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'ui/index.html').read_text('utf-8')
JS = (ROOT/'ui/i18n.js').read_text('utf-8')

class I18nContract210(unittest.TestCase):
    def test_selector_and_format_are_separate(self):
        self.assertIn('id="languageSelect"',HTML)
        self.assertIn('id="numberFormat"',HTML)
        self.assertIn('wmDisplay',HTML)
        self.assertIn('CMI18n.setNumberFormat(formatControl.value,true)',HTML)
        self.assertIn('CMI18n.init()',HTML)
        self.assertIn('CashMiner v2.11',HTML)
        self.assertIn('<script src="/assets/i18n.js"></script>',HTML)
    def test_preserves_log_and_network_payloads(self):
        self.assertIn('ignoredSelectors=',JS)
        for text in ['#minerLog','#peerLog','#recoverySeed','#walletTitle','#walletReceiveAddress']:
            self.assertIn(text,JS)
        self.assertIn('formatSats',JS)
        self.assertIn('normalizeInput',JS)
        self.assertIn('CMI18n.normalizeInput($(\'sendAmount\').value)',HTML)
        self.assertIn('CMI18n.normalizeInput($(\'sendFeeRate\').value)',HTML)
        self.assertIn('fee_rate:CMI18n.normalizeInput',HTML)
        self.assertNotIn('currencySelect',HTML) # fiat pricing remains a later feature
    def test_network_route_serves_local_asset(self):
        src=(ROOT/'src/cashminer/app/server.py').read_text('utf-8')
        self.assertIn("url.path=='/assets/i18n.js'",src)
        self.assertIn("'ui'/'i18n.js'",src)

if __name__=='__main__': unittest.main()

class PersistedDisplayPreferences210(unittest.TestCase):
    def test_restart_reads_locale_from_settings_json(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':folder}):
                with patch.object(app_server,'PREF_FILE',Path(folder)/'settings.json'):
                    service=app_server.CashMinerService()
                    result=service.set_prefs({'ui_language':'en','number_format':'es'})
                    self.assertEqual(result['ui_language'],'en')
                    self.assertEqual(result['number_format'],'es')
                    self.assertEqual(app_server._prefs_read()['ui_language'],'en')
                    self.assertEqual(app_server._prefs_read()['number_format'],'es')
                    service2=app_server.CashMinerService()
                    self.assertEqual(service2.prefs['ui_language'],'en')
                    self.assertEqual(service2.prefs['number_format'],'es')
                    with self.assertRaises(ValueError):service2.set_prefs({'ui_language':'xx'})
                    with self.assertRaises(ValueError):service2.set_prefs({'number_format':'invalid'})
