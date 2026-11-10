"""Pruebas del bridge: nunca inicia minería ni conecta a Internet."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.mining.bridge import MiningSettings,prepare_runtime,project_root,native_libraries
from cashminer.wallet.legacy_hd import address_from_secret

class MinerBridgeTests(unittest.TestCase):
    def test_engine_bundled_and_cpu_fixed(self):
        source=project_root()/'mining_engine'/'miner.py'
        self.assertTrue(source.is_file())
        s=source.read_text('utf-8')
        self.assertIn('device_type=\'cpu\'',s)
        self.assertIn('CASHMINER2_REWARD_POOL_FILE',s)
        self.assertIn('cashaddr_to_scriptpubkey(args.miner_address)',s)

    def test_runtime_has_all_imported_modules_and_starts_importing(self):
        # Reproduce exactamente el entorno de ejecución de la app, NO el
        # árbol de código fuente, donde una dependencia olvidada sí existe.
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {'CASHMINER2_DATA_DIR': td}):
                folder, _ = prepare_runtime()
                self.assertTrue((folder / 'fablous' / 'observer.py').is_file())
                env = os.environ.copy()
                env.pop('PYTHONPATH', None)
                completed = subprocess.run(
                    [sys.executable, '-c', 'import miner; import fablous.observer'],
                    cwd=str(folder), env=env, capture_output=True, text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_validation_without_private_key(self):
        a=address_from_secret(1,'tempnet_fablous_2026')
        m=MiningSettings(network='tempnet_fablous_2026',reward_address=a,cpu_percent=0,gpu_percent=25)
        m.validate()
        self.assertNotIn('private_key',str(m))
        with self.assertRaises(ValueError):
            MiningSettings(network='tempnet_fablous_2026',reward_address=a,cpu_percent=0,gpu_percent=0).validate()
        with self.assertRaises(ValueError):
            MiningSettings(network='tempnet_fablous_2026',reward_address=a,cpu_percent=101,gpu_percent=25).validate()

    def test_runtime_independent_from_original(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td,'CASHMINER2_LEGACY_DIR':''}):
                folder,libraries=prepare_runtime()
                self.assertTrue((folder/'miner.py').is_file())
                self.assertEqual(set(libraries),{'bch_hashscan.dll','bch_hashscan_cuda.dll','bch_hashscan_opencl.dll'})
                self.assertFalse((folder/'tempnet_wallet.json').exists())

if __name__=='__main__':unittest.main()
