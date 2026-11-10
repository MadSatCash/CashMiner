"""v2.11.1: frontend fiat entry is rounded once to exact satoshis; backend unchanged."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text(encoding='utf-8')

class TestSendUnits2111(unittest.TestCase):
    def test_contract_safety_and_anti_translate(self):
        self.assertIn('<html lang="es" translate="no">',HTML)
        self.assertIn('name="google" content="notranslate"',HTML)
        self.assertIn('id="sendUnit"',HTML)
        self.assertIn('id="sendFiatHint"',HTML)
        self.assertIn('sendUnitMode',HTML)
        self.assertIn("if(c.network!=='mainnet'&&sendUnitMode!=='bch')",HTML)
        self.assertIn("amount_bch:sendMaxMode?'':ensureFiatAmountPrepared()",HTML)
        self.assertIn('sendFiatInputValue',HTML)
        self.assertIn('handleFiatCurrencyChange',HTML)
        self.assertIn('CashMiner v2.17.1',HTML)
        # The actual transaction builder must remain exclusively BCH-based.
        self.assertNotIn('fiat_currency',(ROOT/'src/cashminer/wallet/send.py').read_text())
        self.assertNotIn('fiat_currency',(ROOT/'mining_engine/miner.py').read_text())

    @unittest.skipUnless(shutil.which('node'),'Requires Node.js')
    def test_exact_conversion_rounding_locales_and_rate_snapshot(self):
        code=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(process.argv[1],'utf8');
let loc='en-US';
const normalize=(v)=>{const s=String(v).trim(),dec=loc==='es-AR'?',':'.',grp=loc==='es-AR'?'.':',';
 const validA=new RegExp('^\\d+(?:\\'+dec+'\\d+)?$');
 const validB=new RegExp('^\\d{1,3}(?:\\'+grp+'\\d{3})+(?:\\'+dec+'\\d+)?$');
 if(!validA.test(s)&&!validB.test(s))throw Error('invalid');
 return s.split(grp).join('').replace(dec,'.')};
const document={getElementById:()=>null,querySelectorAll:()=>[],dispatchEvent:()=>{}};
const window={CMI18n:{getLocale:()=>loc,getLanguage:()=>loc==='es-AR'?'es':'en',normalizeInput:normalize}};
vm.runInNewContext(src,{window,document,Date,Intl,Number,BigInt,Promise,CustomEvent:class {}});
const f=window.CMFiat;
const fresh=Date.now();
f.init(async()=>({rates:{USD:240.35,ARS:350000,BMD:1e-6},as_of:{USD:fresh,ARS:fresh,BMD:fresh},source:'mock',degraded:[]}));
(async()=>{
 await f.refresh(true);
 assert.strictEqual(f.getQuote().currency,'USD');
 assert.strictEqual(f.fiatToSats('240.35',f.getQuote()),'100000000');
 assert.strictEqual(f.satsToBch('100000001'),'1.00000001');
 assert.strictEqual(f.fiatToSats('0.00000120175',f.getQuote()),'1');
 assert.strictEqual(f.fiatToSats('0',f.getQuote()),null);
 assert.throws(()=>f.fiatToSats('-1',f.getQuote()));
 assert.strictEqual(f.fiatToSats('100000000000000000000000',f.getQuote()),null);
 const held=f.getQuote();
 assert.strictEqual(f.fiatToSats('240.35',held),'100000000');
 f.hydrate('ARS');loc='es-AR';
 assert.strictEqual(f.fiatToSats('350.000,00',f.getQuote()),'100000000');
 assert.strictEqual(f.fiatToSats('175.000,00',f.getQuote()),'50000000');
 assert.strictEqual(f.fiatFromSats('100000000',f.getQuote()),'350000');
 assert.strictEqual(f.getQuote().currency,'ARS');
 assert.throws(()=>f.fiatToSats('240.35',held)); // invalid for ES locale
 assert.strictEqual(f.fiatToSats('240,35',held),'100000000');
 const aged={...held,asOf:fresh-18*60000};
 assert.strictEqual(f.quoteAge(aged).text,'18m');
 assert.strictEqual(f.quoteAge(aged).stale,true);
 const veryCheap={rate:1e-6,currency:'BMD',asOf:fresh,source:'mock'};
 assert.strictEqual(f.fiatToSats('0,000001',veryCheap),'100000000');
 assert.strictEqual(f.satsToBch(f.fiatToSats('0,000001',veryCheap)),'1');
 assert.strictEqual(f.fiatToSats('1,0',null),null);
 assert.throws(()=>f.fiatToSats('not a number',held));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        run=subprocess.run(['node','-e',code,str(ROOT/'ui/fiat.js')],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)

if __name__=='__main__':unittest.main()
