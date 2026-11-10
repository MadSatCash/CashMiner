"""Regresiones visuales v2.7.1 e identidad; no red externa ni claves."""
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image
import unittest
from unittest.mock import patch
from cashminer.app import server as app_server

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui'/'index.html').read_text('utf-8')

class Branding271(unittest.TestCase):
    def test_simple_header_without_redundant_controls(self):
        self.assertNotIn('<header class="masthead">',HTML)
        self.assertNotIn('id="globalStatus"',HTML)
        self.assertNotIn('id="addWallet"',HTML)
        self.assertNotIn('Mis billeteras</h3>',HTML)
        self.assertNotIn('BILLETERA SELECCIONADA',HTML)
        self.assertEqual(HTML.count('id="walletGear"'),1)
        self.assertIn("$('walletGear').onclick=openWalletManager",HTML)
        self.assertNotIn("$('addWallet').onclick",HTML)
        self.assertIn('id="walletList"',HTML)
        self.assertIn('id="walletTitle"',HTML)
        self.assertIn('class="miners-title"',HTML)
        self.assertIn('class="wallet-dashboard-title"',HTML)
        self.assertIn('.miners-title{height:66px',HTML)
        self.assertIn('.wallet-dashboard-head{min-height:66px',HTML)
    def test_png_and_multisize_ico(self):
        png=ROOT/'assets/Logo.png'
        ico=ROOT/'assets/CashMiner.ico'
        self.assertTrue(png.is_file());self.assertTrue(ico.is_file())
        with Image.open(png) as i:
            self.assertEqual(i.size,(1254,1254))
            self.assertIn('A',i.getbands())
            self.assertEqual(i.getpixel((0,0))[3],0)
        with Image.open(ico) as i:
            self.assertEqual(set(i.info.get('sizes',[])),set((n,n) for n in (16,20,24,32,40,48,64,128,256)))
        self.assertIn('href="/favicon.ico"',HTML)
        self.assertIn('href="/assets/icon_16.png"',HTML)
        self.assertIn('href="/assets/icon_32.png"',HTML)
        self.assertIn("'/assets/icon_32.png'",(ROOT/'src/cashminer/app/server.py').read_text())
    def test_browser_launcher_has_no_native_webview_dependency(self):
        source=(ROOT/'src/cashminer/app/server.py').read_text()
        self.assertNotIn('import webview',source)
        self.assertNotIn('webview.start(',source)
        self.assertFalse((ROOT/'INICIAR_WINDOWS_CON_ICONO.bat').exists())
        self.assertNotIn('pywebview',(ROOT/'requirements.txt').read_text())
        self.assertIn('--user-data-dir=',source)
        self.assertIn('--disable-background-mode',source)
        self.assertIn('proc.wait()',source)
        self.assertIn('server.service.stop_all()',source)
    def test_all_small_icons_are_real_png(self):
        for n in (16,32,48,64,128,256):
            with Image.open(ROOT/f'assets/icon_{n}.png') as img:
                self.assertEqual(img.size,(n,n))

if __name__=='__main__':unittest.main()
