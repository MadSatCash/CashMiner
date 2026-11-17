"""Amount editor regressions and exact server-side BCH precision."""
import shutil
import subprocess
import unittest
from pathlib import Path
from cashminer.wallet.send import WalletSender

ROOT=Path(__file__).resolve().parents[1]

class Amount2172(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Requires Node.js')
    def test_real_javascript_editor_events(self):
        run=subprocess.run(['node','--test',str(ROOT/'tests/test_amount_2172.js')],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)

    def test_backend_rejects_excess_decimals_even_when_zero(self):
        for text in ['1.123456789','1.000000000','20999999.999999999']:
            with self.subTest(text=text),self.assertRaises(ValueError):WalletSender.parse_amount(text)
        self.assertEqual(WalletSender.parse_amount('1.12345678'),112345678)
        self.assertEqual(WalletSender.parse_amount('20999999.99999999'),2099999999999999)
