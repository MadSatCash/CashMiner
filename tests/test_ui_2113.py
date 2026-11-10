"""v2.11.3: fiat unit quote, scroll-free balances, mobile tab contract."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'ui' / 'index.html').read_text(encoding='utf-8')
I18N = (ROOT / 'ui' / 'i18n.js').read_text(encoding='utf-8')


class Ui2113Contract(unittest.TestCase):
    def test_quote_uses_current_fiat_provider_not_arbitrary_price(self):
        self.assertIn('id="fiatOneBchRate"', HTML)
        self.assertIn("CMFiat.html('100000000','mainnet')", HTML)
        self.assertIn("el.hidden=network!=='mainnet'", HTML)
        self.assertIn('updateOneBchRate(c.network)', HTML)

    def test_balance_never_scrolls(self):
        rule = HTML.split('/* v2.11.1: stable one-line balances', 1)[1].split('/* v2.11.3:', 1)[0]
        for selector in ('.wallet-aggregate strong', '.wallet-balance-row .balance'):
            segment = rule.split(selector + '{', 1)[1].split('}', 1)[0]
            self.assertNotIn('overflow-x:auto', segment)
            self.assertNotIn('overflow-y:auto', segment)
            self.assertIn('overflow:visible', segment)
        self.assertIn('function fitWalletBalances()', HTML)
        self.assertIn('range.getBoundingClientRect().width', HTML)

    def test_mobile_view_defaults_to_wallet_and_preserves_dom(self):
        self.assertIn('id="appLayout" data-view="wallet"', HTML)
        self.assertIn("let selectedMobileView='wallet'", HTML)
        self.assertIn('id="viewWalletTab"', HTML)
        self.assertIn('id="viewMinerTab"', HTML)
        self.assertIn('.layout[data-view="wallet"]>.miners-pane{display:none}', HTML)
        self.assertIn('.layout[data-view="miner"]>.wallet-dashboard{display:none}', HTML)
        self.assertIn('function setMobileView(view)', HTML)
        self.assertIn("'Billetera':'Wallet'", I18N)
        self.assertIn("'Minero':'Miner'", I18N)

    def test_prior_mainnet_notice_stays_removed(self):
        self.assertNotIn('sendMainnetRisk', HTML)
        self.assertNotIn('mainnet-risk-ack', HTML)
        self.assertIn("api('/api/wallet/send/prepare'", HTML)
        self.assertIn('id="sendUnit"', HTML)


if __name__ == '__main__':
    unittest.main()
