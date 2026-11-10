"""Regression coverage for v2.10.1 UI-only translation audit."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui/index.html").read_text(encoding="utf-8")
I18N = (ROOT / "ui/i18n.js").read_text(encoding="utf-8")

class I18nRegression2101(unittest.TestCase):
    def test_version_and_only_ui_assets_changed(self):
        self.assertIn('CashMiner v2.17.1', HTML)
        self.assertIn('version = "2.17.1"', (ROOT / 'pyproject.toml').read_text())
    def test_input_placeholder_not_ignored(self):
        self.assertNotIn('#sendAmount,', I18N.split('ignoredSelectors=',1)[1].split(';',1)[0])
        self.assertIn("'Monto tBCH':'Amount tBCH'", I18N)
    def test_protected_logs_and_secrets(self):
        self.assertIn('#minerLog', I18N)
        self.assertIn('#peerLog', I18N)
        self.assertIn('#recoverySeed', I18N)
        self.assertIn('ATTR_ONLY', I18N)
        self.assertIn('#walletReceiveAddress', I18N)
    def test_reported_missing_texts_present(self):
        for text in ('Se aplica al próximo arranque en modalidad P2P-tip.',
            'Exclusivos del minero P2P-tip', 'Explora endpoints por DNS y getaddr',
            'Última actividad técnica:', 'No la compartas', 'Eventos del minero:',
            'Minimum peers: value must be between 1 and 80',
            'No se pudo abrir el navegador predeterminado',
            'Copiar dirección #'):
            self.assertIn(text, I18N)
    @unittest.skipUnless(shutil.which('node'), 'Node not installed')
    def test_dynamic_translation_js_and_reverse_switch(self):
        # Run just the i18n module in a tiny mock document. No network or wallet code.
        script = r"""
const fs=require('fs'),vm=require('vm');
const doc={documentElement:{},getElementById(){return null},dispatchEvent(){}};
const store=new Map(),ctx={window:{},document:doc,localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},queueMicrotask(){},CustomEvent:class {}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const tr=ctx.window.CMI18n;
tr.setLanguage('en');
const cases=[
 ['Monto tBCH','Amount tBCH'],
 ['Se aplica al próximo arranque en modalidad P2P-tip. Entero de 1 a 80; 2 es el valor inicial, 1 es experimental y 0 no está permitido. Si la red no ofrece suficientes peers compatibles, no se inicia la minería.',
  'Applies on the next start in P2P-tip mode. Enter an integer from 1 to 80; 2 is the default, 1 is experimental and 0 is not allowed. If the network has too few compatible peers, mining will not start.'],
 ['CPU · 20 hilos · Nativa','CPU · 20 threads · Native'],
 ['Recepción: 2 · Cambio: 3 · Total: 5','Receive: 2 · Change: 3 · Total: 5'],
 ['Último handshake satisfactorio: Nunca','Last successful handshake: Never'],
 ['Cambio: 0,00050000 tBCH · 2 entradas','Change: 0,00050000 tBCH · 2 inputs'],
 ['Mínimo de peers: el valor debe estar entre 1 y 80','Minimum peers: value must be between 1 and 80'],
 ['Última actividad técnica: Sin registrar. Estado: conectado','Last technical activity: Not recorded. Status: connected'],
 [". Quien tenga este secreto puede gastar los fondos de esta billetera.  No la compartas, fotografíes ni guardes solamente en la PC. Ruta: m/44'/1'/0'.",
  ". Anyone with this secret can spend the funds in this wallet. Do not share it, photograph it, or store it only on this PC. Path: m/44'/1'/0'."],
];
for(const [source,target] of cases)if(tr.t(source)!==target)throw Error(JSON.stringify({source,actual:tr.t(source),expected:target}));
const address='bchtest:qrp23yp4n6ypxg4e4jn4d099x4xnefrsygp5mylryx';if(tr.t(address)!==address)throw Error('Address changed');
tr.setLanguage('es');for(const [source] of cases)if(tr.t(source)!==source)throw Error('Spanish original changed');
tr.setLanguage('en');if(tr.t('Monto tBCH')!=='Amount tBCH')throw Error('Switch back failed');
"""
        # Keep the JS source in a temporary argument file: node -e <script> <i18n.js>
        res=subprocess.run(['node','-e',script,str(ROOT/'ui/i18n.js')],capture_output=True,text=True)
        self.assertEqual(res.returncode,0,res.stderr)
