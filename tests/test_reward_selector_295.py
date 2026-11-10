"""CashMiner v2.9.5: one reward selector and non-intrusive mining status."""
import unittest
from pathlib import Path

HTML=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text('utf-8')
CONFIG=HTML.split('function openMineConfig(){',1)[1].split('`,true);',1)[0]
CARDS=HTML.split('function renderMinerCards(c){',1)[1].split('function draw(){',1)[0]

class RewardSelector295(unittest.TestCase):
    def test_one_section_with_many_recipients_not_old_radio_pair(self):
        self.assertIn('id="miningRewardDetails"',CONFIG)
        self.assertNotIn('id="miningRewardDetails" open', CONFIG)
        self.assertIn('id="rewardRows"',CONFIG)
        self.assertIn('id="addRewardDestination"',CONFIG)
        self.assertIn('id="saveRewardDistribution"',CONFIG)
        self.assertNotIn('name="miningTarget"',CONFIG)
        self.assertNotIn('id="miningWallet"',CONFIG)

    def test_rewards_persist_via_original_settings_and_compatibility_choice(self):
        self.assertIn("await api('/api/settings',{network:current.miner_network,reward_destinations:plan,",HTML)
        self.assertIn("await api('/api/miner/select-wallet',{network:current.miner_network,id:plan[0].wallet_id})",HTML)
        self.assertIn('fixed_address:',HTML)
        self.assertIn('function pendingRewardPlan()',HTML)
        self.assertIn('data-reward-wallet',HTML)

    def test_log_and_explorer_have_divider(self):
        self.assertIn('</pre>\n</div></details>\n<hr class="hr" aria-hidden="true">\n<details id="explorerDetails">',CONFIG)

    def test_start_stop_status_in_card_not_success_toast(self):
        self.assertIn("await api('/api/miner/start',{network:net})",CARDS)
        self.assertIn("await api('/api/miner/stop',{network:net})",CARDS)
        self.assertNotIn("notice('Iniciando minería",CARDS)
        self.assertNotIn("notice('Deteniendo minería",CARDS)
        self.assertIn('class="activity-message"',CARDS)
        self.assertIn("notice(e.message,true)",HTML)

if __name__=='__main__':unittest.main()
