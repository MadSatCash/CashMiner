"""Version 2.8.3: no Send modal, reusable inline send form."""
from pathlib import Path
import unittest

HTML=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text(encoding='utf8')

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

if __name__=='__main__':unittest.main()
