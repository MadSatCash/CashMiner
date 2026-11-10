"""Android must reuse shared application policy and preserve later user choices."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server
from cashminer.platform.android_runtime import _prepare_preferences


class AndroidDefaultsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for change in (patch.object(server,'PREF_FILE',self.root/'settings.json'),
                       patch.dict(os.environ,{'CASHMINER_DATA_DIR':temp.name})):
            change.start();self.addCleanup(change.stop)

    def test_new_install_reuses_windows_policy_and_cpu_default(self):
        shared=server._prefs_read();_prepare_preferences(server,self.root)
        actual=server._prefs_read()
        for key in ('wallet_network','network','cpu_percent','explorer_auto_master',
                    'explorer_continuous_master','explorer_auto_by_network'):
            self.assertEqual(actual[key],shared[key],key)
        for network,cfg in shared['miner_settings'].items():
            for key,value in cfg.items():
                if key not in ('gpu_percent','hardware_controls_v2'):
                    self.assertEqual(actual['miner_settings'][network][key],value,(network,key))
            self.assertEqual(actual['miner_settings'][network]['gpu_percent'],0)

    def test_upgrade_restores_forced_off_masters_once_preserving_other_choices(self):
        prefs=server._prefs_read()
        prefs.update(explorer_auto_master=False,explorer_continuous_master=False,wallet_network='testnet3')
        prefs['explorer_auto_by_network']['chipnet']=False
        prefs['miner_settings']['testnet3'].update(cpu_percent=100,gpu_percent=0,hardware_controls_v2=True,peer_source='sqlite')
        server._prefs_save(prefs);(self.root/'android-initialized').touch()
        _prepare_preferences(server,self.root);actual=server._prefs_read()
        self.assertTrue(actual['explorer_auto_master']);self.assertTrue(actual['explorer_continuous_master'])
        self.assertEqual(actual['wallet_network'],'testnet3')
        self.assertFalse(actual['explorer_auto_by_network']['chipnet'])
        self.assertEqual(actual['miner_settings']['testnet3']['cpu_percent'],100)
        self.assertEqual(actual['miner_settings']['testnet3']['peer_source'],'sqlite')
        actual.update(explorer_auto_master=False,explorer_continuous_master=False)
        server._prefs_save(actual);_prepare_preferences(server,self.root)
        again=server._prefs_read()
        self.assertFalse(again['explorer_auto_master']);self.assertFalse(again['explorer_continuous_master'])


if __name__=='__main__':unittest.main()
