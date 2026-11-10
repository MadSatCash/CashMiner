"""v2.5.0: each left-hand panel has its own correctly wired network selector."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
SERVER = (ROOT / "src" / "cashminer" / "app" / "server.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "src" / "cashminer" / "mining" / "bridge.py").read_text(encoding="utf-8")


class NetworkPanelUiContract(unittest.TestCase):
    def test_wallet_selector_at_upper_left_of_wallet_panel(self):
        panel = HTML.split('<section id="walletDashboard" class="pane wallet-dashboard"', 1)[1].split('</main>', 1)[0]
        self.assertIn('id="walletNetworkSelect"', panel)
        self.assertIn('for="walletNetworkSelect"', panel)
        self.assertLess(panel.index('id="walletNetworkSelect"'), panel.index('id="walletList"'))

    def test_miner_dashboard_has_per_network_toggle_and_gear(self):
        self.assertIn('id="minerCards"',HTML)
        self.assertIn('data-miner-toggle=',HTML)
        self.assertIn('data-miner-gear=',HTML)
        self.assertIn('renderMinerCards(c)',HTML)
        self.assertIn('c.networks.map(net=>',HTML)

    def test_no_old_global_miner_selector_or_floating_tab(self):
        self.assertNotIn('<div class="network-tab"',HTML)
        self.assertNotIn('id="minerNetworkSelectInline"',HTML)
        self.assertEqual(HTML.count('id="walletNetworkSelect"'),1)

    def test_network_contexts_use_independent_endpoints(self):
        self.assertIn("api('/api/wallet/network',{network:net})",HTML)
        self.assertNotIn("api('/api/network'",HTML)
        self.assertIn('openMinerSettingsFor(net)',HTML)
        self.assertIn('minerViewNetwork=net',HTML)
        self.assertIn("api('/api/miner/start',{network:net})",HTML)
        self.assertIn("api('/api/miner/stop',{network:net})",HTML)
        self.assertIn('self.sessions[network]',SERVER)
        self.assertIn("self.prefs['miner_settings'][network]",SERVER)

    def test_stopping_one_miner_does_not_disable_other_networks(self):
        self.assertIn('const stopping=m.miner_state',HTML)
        self.assertIn("${stopping?'disabled':''}",HTML)
        self.assertIn('MINING_MODES = {',BRIDGE)
        self.assertIn("'testnet4': ('p2p-tip', 'rpc', 'pool')",BRIDGE)

    def test_release_version_identifiers(self):
        self.assertIn("'version':'2.17.1'",SERVER)
        self.assertIn("server_version='CashMiner/2.17.1'",SERVER)
        self.assertIn('CashMiner v2.17.1',HTML)

if __name__ == '__main__':
    unittest.main()
