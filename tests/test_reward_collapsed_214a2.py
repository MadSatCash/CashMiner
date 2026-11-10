"""v2.16: rewards panel starts collapsed without disabling the native toggle."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'ui' / 'index.html').read_text('utf-8')
CONFIG = HTML.split('function openMineConfig(){', 1)[1].split('`,true);', 1)[0]


class RewardCollapsed214A2(unittest.TestCase):
    def test_reward_section_is_native_details_closed_by_default(self):
        self.assertIn('<details class="settings-section" id="miningRewardDetails"><summary>Destino de recompensas</summary>', CONFIG)
        self.assertNotIn('id="miningRewardDetails" open', CONFIG)
        self.assertIn('</div></details>', CONFIG)

    def test_editing_controls_and_event_handlers_unchanged(self):
        for component in ('id="rewardRows"', 'id="addRewardDestination"', 'id="saveRewardDistribution"'):
            self.assertIn(component, CONFIG)
        self.assertIn("$('saveRewardDistribution').onclick", HTML)
        self.assertIn("$('addRewardDestination').onclick", HTML)


if __name__ == '__main__':
    unittest.main()
