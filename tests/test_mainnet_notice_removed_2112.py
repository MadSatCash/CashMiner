"""v2.11.2: remove only the redundant Mainnet acknowledgment checkbox.

Keep the established two-step prepare -> confirm -> broadcast flow intact.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text(encoding='utf-8')
I18N=(ROOT/'ui/i18n.js').read_text(encoding='utf-8')


class MainnetNoticeRemoved2112(unittest.TestCase):
    def test_no_extra_checkbox_or_gate_remains(self):
        for source in (HTML,I18N):
            for obsolete in ('sendMainnetRisk','sendMainnetRiskRow',
                             'Confirmá el aviso de Mainnet antes de continuar',
                             'Entiendo que esta versión no fue auditada ni probada con BCH reales',
                             'I understand this version has not been audited or tested with real BCH'):
                self.assertNotIn(obsolete,source)

    def test_existing_confirmation_and_transaction_flow_untouched(self):
        self.assertIn("api('/api/wallet/send/prepare'",HTML)
        self.assertIn("modal('Confirmar envío · '",HTML)
        self.assertIn('id="sendConfirm"',HTML)
        self.assertIn("api('/api/wallet/send/broadcast'",HTML)
        self.assertIn('amount_bch:sendMaxMode?\'\':ensureFiatAmountPrepared()',HTML)
        self.assertIn('if(w.scan_state!==\'synced\'',HTML)

if __name__=='__main__':
    unittest.main()
