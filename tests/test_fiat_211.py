"""v2.11: rates are display-only and cannot alter wallet/mining internals."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app.fiat import CURRENCIES, FiatQuotes, TTL_SECONDS
from cashminer.app import fiat
from cashminer.app import server as app_server

ROOT=Path(__file__).resolve().parents[1]

class TestFiat211(unittest.TestCase):
    def test_catalog_and_endpoints(self):
        self.assertEqual(len(CURRENCIES),50)
        self.assertEqual(len(set(CURRENCIES)),50)
        self.assertTrue({'ARS','USD','EUR','BRL','COP','PYG','BOB','VES'} <= set(CURRENCIES))
        source=(ROOT/'src/cashminer/app/server.py').read_text()
        self.assertIn("url.path=='/api/fiat/rates'",source)
        self.assertIn("url.path=='/assets/fiat.js'",source)
        self.assertIn("'fiat_currency'",source)
        self.assertIn('s.fiat_quotes.snapshot()',source)

    def test_multiple_providers_yadio_override_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            f=FiatQuotes(Path(d)/'rates.json',clock=lambda:2000)
            with patch.object(fiat,'_fetch_coingecko',side_effect=OSError), \
                 patch.object(fiat,'_fetch_coinbase',return_value={'USD':250,'EUR':230,'ARS':255000}), \
                 patch.object(fiat,'_fetch_bitpay',side_effect=AssertionError('Fallback should stop at Coinbase')), \
                 patch.object(fiat,'_fetch_yadio',return_value={'ARS':1200,'VES':900}):
                self.assertTrue(f.refresh_now())
            snap=f.snapshot(refresh=False)
            self.assertEqual(snap['source'],'Coinbase + Yadio')
            self.assertEqual(snap['rates']['ARS'],300000)
            self.assertEqual(snap['rates']['VES'],225000)
            self.assertEqual(snap['rates']['EUR'],230)
            self.assertEqual(snap['as_of']['ARS'],2000000)
            self.assertFalse(snap['degraded'])
            reopened=FiatQuotes(Path(d)/'rates.json',clock=lambda:2001)
            self.assertEqual(reopened.snapshot(refresh=False)['rates']['ARS'],300000)

    def test_cached_yadio_remains_stale_even_after_fresh_base_quote(self):
        clock=[2000]
        with tempfile.TemporaryDirectory() as d:
            f=FiatQuotes(Path(d)/'rates.json',clock=lambda:clock[0])
            with patch.object(fiat,'_fetch_coingecko',return_value={'USD':300}), \
                 patch.object(fiat,'_fetch_yadio',return_value={'ARS':1400}):
                self.assertTrue(f.refresh_now())
            clock[0]=2650
            with patch.object(fiat,'_fetch_coingecko',return_value={'USD':310}), \
                 patch.object(fiat,'_fetch_yadio',side_effect=OSError):
                self.assertTrue(f.refresh_now())
            snap=f.snapshot(refresh=False)
            self.assertEqual(snap['as_of']['USD'],2650000)
            self.assertEqual(snap['as_of']['ARS'],2000000)
            self.assertEqual(snap['rates']['ARS'],434000)
            self.assertEqual(f.last_fetch,2650000)

    def test_failed_provider_keeps_cached_quote_and_no_fake_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            f=FiatQuotes(Path(d)/'rates.json',clock=lambda:1200)
            f.rates={'USD':250};f.as_of={'USD':1000000};f.source='previous'
            with patch.object(fiat,'_fetch_coingecko',side_effect=TimeoutError), \
                 patch.object(fiat,'_fetch_coinbase',side_effect=TimeoutError), \
                 patch.object(fiat,'_fetch_bitpay',side_effect=TimeoutError):
                self.assertFalse(f.refresh_now())
            self.assertEqual(f.snapshot(refresh=False)['as_of']['USD'],1000000)
            self.assertEqual(f.snapshot(refresh=False)['rates']['USD'],250)

    def test_bad_remote_rates_and_corrupt_cache_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rates.json'
            p.write_text('{this is not JSON')
            f=FiatQuotes(p,clock=lambda:1000)
            self.assertEqual(f.snapshot(refresh=False)['rates'],{})
            self.assertEqual(fiat._clean_rates({'USD':float('nan'),'ARS':-1,'EUR':0,'COP':10,'BAD':99}),{'COP':10})

    def test_settings_persist_and_invalid_codes_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(app_server,'PREF_FILE',Path(d)/'settings.json'):
                prefs=app_server._prefs_read()
                self.assertEqual(prefs['fiat_currency'],'USD')
                prefs['fiat_currency']='ARS'
                app_server._prefs_save(prefs)
                self.assertEqual(app_server._prefs_read()['fiat_currency'],'ARS')
                prefs['fiat_currency']='INVALID'
                app_server._prefs_save(prefs)
                self.assertEqual(app_server._prefs_read()['fiat_currency'],'USD')

    def test_ui_only_protection(self):
        html=(ROOT/'ui/index.html').read_text()
        self.assertIn('CashMiner v2.11',html)
        self.assertIn('fiatCurrencySelect',html)
        self.assertIn('walletAggregateFiat',html)
        self.assertIn('balanceFiat',html)
        self.assertIn('sendFiatHint',html)
        self.assertIn("network!=='mainnet'",(ROOT/'ui/fiat.js').read_text())
        self.assertIn('inputToSats',html)
        self.assertNotIn('fiat_currency', (ROOT/'src/cashminer/wallet/send.py').read_text())
        self.assertNotIn('fiat_currency', (ROOT/'mining_engine/miner.py').read_text())

    @unittest.skipUnless(shutil.which('node'),'Requires Node.js')
    def test_js_fiat_small_amount_stale_and_excludes_testnets(self):
        script=r"""
const fs=require('fs'),vm=require('vm');
const priceAt=Date.now()-18*60000;
const doc={getElementById(){return null},querySelectorAll(){return []},dispatchEvent(){}};
const ctx={window:{CMI18n:{getLocale:()=> 'es-AR',getLanguage:()=> 'es',normalizeInput:x=>x.replaceAll('.','').replace(',','.')}},
  document:doc,Date,CustomEvent:class {},Intl,BigInt,Number,Promise};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const f=ctx.window.CMFiat;
if(f.CURRENCIES.length!==50)throw Error('Catalog count');
f.hydrate('ARS');
// Inject a real (but fabricated test) rate response through the local API.
f.init(async()=>({rates:{ARS:300000},as_of:{ARS:priceAt},source:'Coinbase + Yadio',degraded:[],ttl_seconds:300}));
(async()=>{
 await f.refresh(true);
 const data=f.details('125000000');
 if(!data.stale||data.ageText!=='18m')throw Error(JSON.stringify(data));
 if(!data.text.includes('375.000')||!data.text.includes('ARS'))throw Error(data.text);
 if(f.html('125000000','testnet3')!=='')throw Error('Testnet fiat leak');
 if(f.inputToSats('1,25000000')!=='125000000')throw Error('Bad sat parsing');
 if(f.inputToSats('MAX')!==null)throw Error('MAX affects fiat conversion');
 if(f.html('125000000','mainnet').indexOf('18m')<0)throw Error('Stale indicator missing');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        run=subprocess.run(['node','-e',script,str(ROOT/'ui/fiat.js')],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
