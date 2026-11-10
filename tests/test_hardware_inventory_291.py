"""Contract checks for the real engine-based hardware inventory (no GPU needed)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.mining import hardware

ROOT = Path(__file__).resolve().parents[1]
KEY_A = 'a' * 64
KEY_B = 'b' * 64


class DeviceInventory291(unittest.TestCase):
    def test_identity_overrides_follow_gpu_not_slot(self):
        old = {'gpus': [
            {'slot':0,'key':KEY_A,'supported':True},
            {'slot':1,'key':KEY_B,'supported':True},
        ]}
        new = {'gpus': [
            {'slot':0,'key':KEY_B,'supported':True},
            {'slot':1,'key':KEY_A,'supported':True},
        ]}
        prefs = {'gpu_overrides':{'0':55,'1':15}, 'gpu_identity_overrides':{KEY_A:30, KEY_B:0}}
        self.assertEqual(hardware.effective_gpu_overrides(prefs,old),{0:30,1:0})
        self.assertEqual(hardware.effective_gpu_overrides(prefs,new),{0:0,1:30})

    def test_removed_gpu_does_not_transfer_its_percentage(self):
        prefs={'gpu_overrides':{'0':99},'gpu_identity_overrides':{KEY_A:60}}
        new={'gpus':[{'slot':0,'key':KEY_B,'supported':True}]}
        self.assertEqual(hardware.effective_gpu_overrides(prefs,new),{})

    def test_legacy_slots_survive_until_user_saves(self):
        prefs={'gpu_overrides':{'0':25,'2':80},'gpu_identity_overrides':{}}
        self.assertEqual(hardware.effective_gpu_overrides(prefs,{'gpus':[]}),{0:25,2:80})

    def test_validate_ids_and_range(self):
        self.assertEqual(hardware.validate_identity_overrides({KEY_A:0,KEY_B:'25'}),{KEY_A:0.0,KEY_B:25.0})
        for bad in ({'evil':25},{KEY_A:-1},{KEY_A:101},{KEY_A:'x'},[]):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                hardware.validate_identity_overrides(bad)

    def test_probe_script_uses_engine_detector_without_mining(self):
        src=(ROOT/'scripts/hardware_probe.py').read_text()
        self.assertIn('miner.detect_gpu_resources()',src)
        self.assertIn('miner.detect_cpu_resources()',src)
        self.assertNotIn('miner.main()',src)

    def test_subprocess_inventory_parses_only_tagged_json(self):
        output={'cpus':[{'index':0,'name':'Test CPU','logical_threads':8}],
                'gpus':[{'slot':0,'key':KEY_A,'name':'Test Radeon','supported':False,
                         'stable_id':True,'backend':None,'backend_index':None}]}
        fake=subprocess.CompletedProcess(args=['python'],returncode=0,
            stdout='unrelated messages\n__CASHMINER_HARDWARE_JSON__'+json.dumps(output)+'\n',stderr='')
        with patch.object(hardware.subprocess,'run',return_value=fake):
            self.assertEqual(hardware.inventory(refresh=True),output)

    def test_ui_has_no_hardcoded_two_slot_inputs(self):
        ui=(ROOT/'ui/index.html').read_text()
        self.assertNotIn('id="gpu0Value"',ui)
        self.assertNotIn('id="gpu1Value"',ui)
        self.assertIn('data-gpu-identity',ui)
        self.assertIn('id="hardwareDevices"',ui)
        self.assertIn('gpu_identity_overrides:identified',ui)
        self.assertIn('data-cpu-percent',ui)
        self.assertNotIn('id="gpuValue"',ui)
        self.assertNotIn('id="cpuValue"',ui)

    def test_native_hash_backends_match_a10_verified_release(self):
        import hashlib
        expected = {
            # CPU and CUDA must remain byte-identical to a9.
            'bch_hashscan.dll': '0bc11363b0f53bcaf0cee1f31e9b55a375405f88bb3b0b7e43890cad240a6f4a',
            'bch_hashscan_cuda.dll': '119a8e2b5baa556c6c69819371b3647ec0016de1dfa0735cec3946f25aa81b31',
            # OpenCL is intentionally rebuilt and validated on Windows.
            'bch_hashscan_opencl.dll': '16475386d89ddc08b24b3cba43076ba42739a6959bcb76c3eb8d41974456c2ea',
        }
        for name, digest in expected.items():
            with self.subTest(backend=name):
                self.assertEqual(hashlib.sha256((ROOT/'native'/name).read_bytes()).hexdigest(),digest)

