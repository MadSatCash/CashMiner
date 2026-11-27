"""Version 2.8.3: no Send modal, reusable inline send form."""
from pathlib import Path
import shutil
import subprocess
import unittest

HTML_PATH=Path(__file__).resolve().parents[1]/'ui/index.html'
HTML=HTML_PATH.read_text(encoding='utf8')

class InlineSendLayout(unittest.TestCase):
    def test_receiving_and_sending_are_separate_inline_sections(self):
        for label in ('walletReceiveSection','walletSendSection','sendAddress','sendAmount',
                      'sendMax','sendFeeRate','sendPrepare'):
            self.assertIn('id="'+label+'"',HTML)
        self.assertNotIn('id="sendBtn"',HTML)
        self.assertNotIn('id="sendAvailable"',HTML)
        self.assertNotIn('id="sendAmountLabel"',HTML)
        self.assertNotIn('class="wallet-balance-label">Saldo disponible',HTML)
        self.assertNotIn('class="wallet-io-title"',HTML)
        self.assertNotIn('id="walletReceiveSection" class="wallet-io-card"',HTML)
        self.assertIn('Enviar a Dirección CashAddr (con prefijo):',HTML)
        self.assertIn('placeholder="Monto tBCH"',HTML)
        self.assertIn('id="sendPrepare" type="button" class="btn primary send-action" disabled>Enviar</button>',HTML)
        self.assertNotIn("modal('Enviar '+coinUnit",HTML)
        self.assertNotIn('Versión experimental. Verificá cuidadosamente el destinatario',HTML)

    def test_guarded_prepare_and_broadcast_still_exist(self):
        self.assertIn("api('/api/wallet/send/prepare'",HTML)
        self.assertIn("api('/api/wallet/send/broadcast'",HTML)
        self.assertIn("modal('Confirmar envío · '",HTML)
        self.assertIn("id=\"sendConfirm\"",HTML)
        self.assertNotIn('sendMainnetRisk',HTML)
        self.assertIn("sendFormContext!==context",HTML)
        self.assertIn("$('sendPrepare').onclick=prepareInlineSend",HTML)
        self.assertIn('totalFormat(aggregate.available_sats)',HTML)

    @unittest.skipUnless(shutil.which('node'),'Requires Node.js')
    def test_synced_wallet_can_prepare_send_while_other_wallet_retries(self):
        self.assertIn("$('sendPrepare').disabled=!canPrepareWalletSend(c,w)",HTML)
        self.assertIn('if(!canPrepareWalletSend(current,w))',HTML)
        code=r'''
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const helpers=html.slice(html.indexOf('function walletElectrumOnline'),html.indexOf('function coinUnit'));
const {canPrepareWalletSend}=vm.runInNewContext(helpers+'\n({canPrepareWalletSend})');
const synced={scan_state:'synced',available_sats:77723};
const retrying={scan_state:'stale',available_sats:90000};
const state={wallets:[synced,retrying],wallet_electrum:{status:'sincronizando'},wallet_capabilities:{send:true}};
assert.equal(canPrepareWalletSend(state,synced),true);
assert.equal(canPrepareWalletSend(state,retrying),false);
assert.equal(canPrepareWalletSend(state,{...synced,available_sats:0}),false);
state.wallet_electrum.status='sin_conexion';
assert.equal(canPrepareWalletSend(state,synced),false);
'''
        result=subprocess.run(['node','-e',code,str(HTML_PATH)],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
