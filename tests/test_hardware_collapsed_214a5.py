"""Hardware settings are collapsible, closed by default and preserve their save logic."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui'/'index.html').read_text(encoding='utf-8')
CONFIG=HTML.split('function openMineConfig(){',1)[1].split('`,true);',1)[0]

class HardwareCollapsed(unittest.TestCase):
    def test_native_details_starts_closed_and_keeps_panel_order(self):
        self.assertIn('<details class="settings-section" id="miningHardwareDetails"><summary>Hardware</summary><div class="details-body">',CONFIG)
        self.assertNotIn('id="miningHardwareDetails" open',CONFIG)
        self.assertLess(CONFIG.index('id="miningModeDetails"'),CONFIG.index('id="miningHardwareDetails"'))
        self.assertLess(CONFIG.index('id="miningHardwareDetails"'),CONFIG.index('id="minPeersDetails"'))
        self.assertIn('Bibliotecas incluidas:',CONFIG)
        self.assertIn('</div></details>\n<details class="settings-section" id="minPeersDetails">',CONFIG)
    def test_hardware_controls_and_save_handlers_remain(self):
        for id in ('hardwareDevices','refreshHardwareBtn','saveMineSettings'):
            self.assertIn('id="'+id+'"',CONFIG)
        for hook in ("showDetectedHardware();", "$('refreshHardwareBtn').onclick", "$('saveMineSettings').onclick"):
            self.assertIn(hook,HTML)
