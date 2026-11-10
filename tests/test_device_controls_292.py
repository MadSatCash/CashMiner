"""v2.9.2: sane per-device defaults and migration (no live GPU needed)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server
from cashminer.mining import hardware

A = 'a' * 64
B = 'b' * 64


class PerDeviceConfig292(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p=patch.object(server,'PREF_FILE',Path(self.temp.name)/'settings.json')
        p.start();self.addCleanup(p.stop)
        e=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.temp.name})
        e.start();self.addCleanup(e.stop)

    def test_new_install_has_conservative_device_defaults_on_each_network(self):
        prefs=server._prefs_read()['miner_settings']
        for network, setting in prefs.items():
            with self.subTest(network=network):
                self.assertEqual(setting['cpu_percent'],0)
                self.assertEqual(setting['gpu_percent'],25)
                self.assertEqual(setting['gpu_identity_overrides'],{})
                self.assertFalse(setting['hardware_controls_v2'])

    def test_migration_discards_global_and_legacy_slots_not_stable_device_choices(self):
        server.PREF_FILE.write_text(json.dumps({'miner_settings':{
          'chipnet':{'cpu_percent':0,'gpu_percent':25,'gpu_overrides':{'0':30},
                     'gpu_identity_overrides':{A:35}}}}), encoding='utf8')
        settings=server._prefs_read()['miner_settings']['chipnet']
        self.assertEqual(settings['cpu_percent'],0)
        self.assertEqual(settings['gpu_percent'],25)
        self.assertEqual(settings['gpu_overrides'],{})
        self.assertEqual(settings['gpu_identity_overrides'],{A:35.0})

    def test_saving_explicit_percentages_retains_them_on_restart(self):
        svc=server.CashMinerService()
        self.addCleanup(svc.stop_all)
        svc.set_prefs({'network':'chipnet','cpu_percent':0,'gpu_percent':20,
                       'gpu_identity_overrides':{A:40,B:0},'gpu_overrides':{},
                       'hardware_controls_v2':True})
        restarted=server._prefs_read()['miner_settings']['chipnet']
        self.assertTrue(restarted['hardware_controls_v2'])
        self.assertEqual(restarted['cpu_percent'],0)
        self.assertEqual(restarted['gpu_percent'],25)
        self.assertEqual(restarted['gpu_identity_overrides'],{A:40,B:0})
        detected={'gpus':[{'slot':0,'key':B,'supported':True},
                          {'slot':1,'key':A,'supported':True},
                          {'slot':2,'key':'c'*64,'supported':True}]}
        self.assertEqual(hardware.effective_gpu_overrides(restarted,detected),{0:0,1:40})
        # GPU #2 receives the internal 25% default from gpu_percent.

    def test_ui_does_not_show_any_global_cpu_gpu_or_inheritance_control(self):
        ui=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text('utf8')
        self.assertNotIn('id="cpuValue"',ui)
        self.assertNotIn('id="gpuValue"',ui)
        self.assertNotIn('placeholder="Global"',ui)
        self.assertNotIn('Control global arriba',ui)
        self.assertIn('data-cpu-percent',ui)
        self.assertIn('data-gpu-identity',ui)
        self.assertIn('hardware_controls_v2:true',ui)
        self.assertIn('cpu_percent:percentage(',ui)


if __name__=='__main__':unittest.main()
