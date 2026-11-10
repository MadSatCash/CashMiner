"""v2.11.4: wallet-only compact narrow-window UI contract."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text('utf8')
I18N=(ROOT/'ui/i18n.js').read_text('utf8')

class CompactWalletUi2114(unittest.TestCase):
    def test_mobile_picker_is_additive_and_desktop_cards_remain(self):
        self.assertIn('id="mobileWalletPicker"',HTML)
        self.assertIn('id="walletList" class="wallet-list"',HTML)
        self.assertIn('.mobile-wallet-picker{display:none}',HTML)
        self.assertIn(' .mobile-wallet-picker{display:block;',HTML)
        self.assertIn(' .wallet-list-column .wallet-list{display:none}',HTML)
        self.assertIn('c.wallets.map(v=>`<option data-cm-no-translate value=',HTML)
        self.assertIn('>${esc(v.name)}</option>',HTML)

    def test_picker_uses_existing_wallet_selection_endpoint(self):
        self.assertIn("$('mobileWalletPicker').addEventListener('change'",HTML)
        self.assertIn("api('/api/wallet/select',{id})",HTML)
        self.assertIn('picker.disabled=!c.wallets.length;',HTML)
        self.assertIn("picker.title=w?w.name:'Seleccionar billetera'",HTML)

    def test_mobile_only_detail_labels_are_translated(self):
        self.assertIn('class="wallet-detail-long">Saldo total:</span>',HTML)
        self.assertIn('class="wallet-detail-short">Total:</span>',HTML)
        self.assertIn('class="wallet-detail-short">Inmaduras:</span>',HTML)
        self.assertIn(' .wallet-detail-short{display:inline}',HTML)
        self.assertIn("'Inmaduras:':'Immature:'",I18N)
        self.assertIn(' .wallet-detail-column{position:relative;',HTML)
        self.assertIn(' .wallet-title-row .wallet-name{display:none}',HTML)

    def test_no_changes_to_payment_controls_or_removed_warning(self):
        self.assertIn('id="sendUnit"',HTML)
        self.assertIn('id="sendPrepare"',HTML)
        self.assertNotIn('sendMainnetRisk',HTML)
        self.assertIn('id="viewWalletTab"',HTML)
        self.assertIn('id="viewMinerTab"',HTML)

if __name__=='__main__':unittest.main()
