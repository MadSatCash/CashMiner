"""v2.9.4: hardware defaults, saved choices and compact mining sections."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server
from cashminer.mining import hardware

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'ui/index.html').read_text('utf8')
A, B = 'a'*64, 'b'*64

class DeviceDefaults294(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.prefs_path = Path(temp.name) / 'settings.json'
        p = patch.object(server, 'PREF_FILE', self.prefs_path)
        p.start()
        self.addCleanup(p.stop)
        e = patch.dict(os.environ, {'CASHMINER2_DATA_DIR': temp.name})
        e.start()
        self.addCleanup(e.stop)

    def test_new_install_defaults_per_network(self):
        settings = server._prefs_read()['miner_settings']
        self.assertTrue(settings)
        for network, values in settings.items():
            with self.subTest(network=network):
                self.assertEqual(values['cpu_percent'], 0)
                self.assertEqual(values['gpu_percent'], 25)
                self.assertEqual(values['gpu_identity_overrides'], {})
                self.assertFalse(values['hardware_controls_v2'])

    def test_per_device_settings_are_not_overwritten_on_upgrade(self):
        self.prefs_path.write_text(json.dumps({'miner_settings':{
            'testnet3': {
                'hardware_controls_v2':True,
                'cpu_percent': 45, 'gpu_percent':20,
                'gpu_identity_overrides': {A: 0, B: 62},
                'gpu_overrides': {},
            },
            'chipnet': {
                'hardware_controls_v2':True,
                'cpu_percent': 0,'gpu_percent':20,
                'gpu_identity_overrides': {A: 15},
            },
        }}), 'utf8')
        settings = server._prefs_read()['miner_settings']
        self.assertEqual(settings['testnet3']['cpu_percent'],45)
        self.assertEqual(settings['chipnet']['cpu_percent'],0)
        self.assertEqual(settings['testnet3']['gpu_identity_overrides'],{A:0,B:62})
        self.assertEqual(settings['chipnet']['gpu_identity_overrides'],{A:15})
        # The old hidden 20% GPU fallback becomes 25%, not existing per-device choices.
        self.assertEqual(settings['testnet3']['gpu_percent'],25)
        self.assertEqual(settings['chipnet']['gpu_percent'],25)
        self.assertEqual(settings['testnet4']['cpu_percent'],0)
        self.assertEqual(settings['testnet4']['gpu_percent'],25)

    def test_explicit_nonlegacy_fallback_is_not_changed(self):
        self.prefs_path.write_text(json.dumps({'miner_settings':{
            'chipnet': {'hardware_controls_v2':True, 'cpu_percent':30,
                        'gpu_percent':55,'gpu_identity_overrides':{A:41}}
        }}),'utf8')
        settings = server._prefs_read()['miner_settings']['chipnet']
        self.assertEqual(settings['cpu_percent'],30)
        self.assertEqual(settings['gpu_percent'],55)
        self.assertEqual(settings['gpu_identity_overrides'],{A:41})

    def test_saved_zero_and_custom_settings_survive_restart_and_order_change(self):
        service = server.CashMinerService()
        self.addCleanup(service.stop_all)
        service.set_prefs({'network':'testnet3','hardware_controls_v2':True,
                          'cpu_percent':0,'gpu_percent':25,
                          'gpu_overrides':{},'gpu_identity_overrides':{A:0,B:75}})
        settings = server._prefs_read()['miner_settings']['testnet3']
        self.assertEqual(settings['cpu_percent'],0)
        self.assertEqual(settings['gpu_percent'],25)
        self.assertEqual(settings['gpu_identity_overrides'],{A:0,B:75})
        detected = {'gpus':[
            {'slot':0,'key':B,'supported':True},
            {'slot':1,'key':A,'supported':True},
            {'slot':2,'key':'c'*64,'supported':True},
            {'slot':3,'key':'d'*64,'supported':False},
        ]}
        self.assertEqual(hardware.effective_gpu_overrides(settings,detected),{0:75,1:0})
        # New compatible GPU #2 uses gpu_percent=25, not some other GPU's saved choice.
        self.assertNotIn(2,hardware.effective_gpu_overrides(settings,detected))

    def test_ui_fallbacks_and_compact_sections(self):
        self.assertIn('Inicial: CPU 0 %, GPU 25 %',HTML)
        self.assertIn('s.hardware_controls_v2?s.cpu_percent:0',HTML)
        self.assertIn('Object.prototype.hasOwnProperty.call(saved,g.key)?saved[g.key]:25',HTML)
        self.assertIn('gpu_percent:25,gpu_overrides:{}',HTML)
        self.assertIn('details.settings-section{padding:0}',HTML)
        self.assertIn('<details class="settings-section" id="miningModeDetails"><summary>',HTML)
        self.assertIn('<details class="settings-section" id="minPeersDetails"><summary>',HTML)
        self.assertIn('<details id="logDetails"><summary>',HTML)

if __name__ == '__main__':
    unittest.main()
