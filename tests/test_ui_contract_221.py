"""La actividad y el contador pertenecen al panel lateral, no al footer."""
import re
import unittest
from pathlib import Path
UI=Path(__file__).resolve().parents[1]/'ui/index.html'
class Ui221Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=UI.read_text('utf8')
    def test_mining_dashboard_left_and_wallet_workspace_right(self):
        x=self.ui
        self.assertIn('id="minerCards"',x)
        self.assertIn('class="pane wallet-dashboard"',x)
        self.assertIn('id="walletList"',x)
        self.assertLess(x.index('id="minerCards"'),x.index('id="walletList"'))
        self.assertIn('data-miner-toggle=',x)
        self.assertIn('data-miner-gear=',x)
        self.assertIn('class="activity-message"',x)
        self.assertIn('class="block-count"',x)
        self.assertIn('m.blocks_in_chain??0',x)
    def test_saved_log_selection_is_not_manual(self):
        self.assertIn('selectedMinerLog=saved.name;manuallySelectedLog=false',self.ui)
        self.assertIn('manuallySelectedLog=true;selectedMinerLog',self.ui)
    def test_persistent_min_peers_option_and_no_start_prompt(self):
        self.assertIn('id="minPeersMining"',self.ui)
        self.assertIn("min_peers_mining:Number($('minPeersMining').value)",self.ui)
        self.assertNotIn('one_peer_consent:answer.one_peer_consent',self.ui)
        self.assertIn('id="mineHistoryList"',self.ui)
if __name__=='__main__':unittest.main()
