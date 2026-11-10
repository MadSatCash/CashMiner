"""v2.8.4: inline wallet-specific settings, general admin and safety invariants."""
import unittest
from pathlib import Path
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text('utf8')

class WalletSettingsInline284(unittest.TestCase):
    def test_toolbar_and_two_views_in_detail_pane(self):
        self.assertIn('id="walletSettingsToggle"',HTML)
        self.assertIn('id="walletNormalContent"',HTML)
        self.assertIn('id="walletSettingsContent"',HTML)
        self.assertIn('aria-pressed="false"',HTML)
        self.assertIn('renderWalletSettingsState(c,w)',HTML)
        self.assertIn("btn.firstElementChild.textContent=walletSettingsMode?'×':'⚙'",HTML)
        self.assertIn("if(walletSettingsKey===key)return;",HTML)
        self.assertIn("walletSettingsMode=false;walletSettingsKey=null;",HTML)

    def test_general_manager_separate_from_existing_wallet_functions(self):
        general=HTML.split('function walletManagerContent(){',1)[1].split('function walletKindLabel(',1)[0]
        for name in ('wmCreate','wmImport','wmDerivation','wmConnection'):
            self.assertIn(f'id="{name}"',general)
        self.assertNotIn('id="wmWallets"',general)
        self.assertNotIn('data-manage-wallet=',general)
        self.assertNotIn('id="recoveryBtn"',general)
        individual=HTML.split('function walletIndividualSettingsContent(w){',1)[1].split('function renderWalletSettingsState(',1)[0]
        for name in ('recoveryBtn','forceRefreshBtn','walletHistoryBtn','renameWalletBtn','deleteWalletBtn'):
            self.assertIn(f'id="{name}"',individual)
        self.assertNotIn('<h3 class="section-title">${esc(w.name)}</h3>',individual)

    def test_sensitive_actions_keep_pre_existing_confirmations(self):
        self.assertIn("askDecision('Revelar secreto privado'",HTML)
        self.assertIn("askDecision('Eliminar billetera · '+managedWallet.name",HTML)
        self.assertIn("expected_name:managedWallet.name,expected_address:managedWallet.first_address",HTML)
        self.assertIn("if(!answer)return;\n  assertWallet();",HTML)
        self.assertIn('showRecoverySeed(result)',HTML)
        self.assertIn('showSendResult(out)',HTML)
        self.assertIn("api('/api/wallet/send/broadcast'",HTML)

    def test_footer_retains_visible_version_without_extra_text_or_link(self):
        self.assertIn('class="footer-info">CashMiner v2.17.1 · Made by <a id="cashriderCredit" href="https://munia.cash/profile/cashrider"',HTML)
        self.assertNotIn('Aplicación local · Conexiones P2P salientes',HTML)
        self.assertNotIn('id="closeApp"',HTML)
        self.assertNotIn('Cerrar CashMiner</button>',HTML)

if __name__=='__main__':unittest.main()
