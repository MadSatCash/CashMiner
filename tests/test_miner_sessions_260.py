"""v2.6: independent runtime sessions, reward destinations and preferences.

Everything runs offline with fake mining subprocesses and public test vectors.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.platform import log_archive
from cashminer.wallet.legacy_hd import address_from_secret
from cashminer.mining.bridge import MinerController


class FakeProcess:
    def poll(self): return None


class Multisession260(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.temp.name})
        self.env.start();self.addCleanup(self.env.stop)
        self.path=patch.object(app_server,'PREF_FILE',Path(self.temp.name)/'settings.json')
        self.path.start();self.addCleanup(self.path.stop)
        self.service=app_server.CashMinerService()
        self.addCleanup(self.service.stop_all)

    def test_six_networks_and_independent_preferences(self):
        s=self.service
        self.assertEqual(len(s.sessions),6)
        self.assertEqual(s.state()['active_mining_count'],0)
        s.set_prefs({'network':'testnet3','cpu_percent':10,'gpu_percent':15,
                     'mining_target_mode':'address','fixed_address':address_from_secret(1,'testnet3')})
        s.set_prefs({'network':'testnet4','cpu_percent':23,'gpu_percent':8,
                     'mining_target_mode':'address','fixed_address':address_from_secret(2,'testnet4')})
        # La vista solicita la red; no altera el servicio
        self.assertEqual(s.state('testnet3')['settings']['cpu_percent'],10)
        # La segunda vista solicita otra red
        self.assertEqual(s.state('testnet4')['settings']['cpu_percent'],23)
        self.assertNotEqual(s.prefs['miner_settings']['testnet3']['fixed_address'],
                            s.prefs['miner_settings']['testnet4']['fixed_address'])
        self.assertNotIn('fixed_address',json.dumps(s.prefs['wallet_derivation_defaults']))
        new=app_server._prefs_read()
        self.assertEqual(new['miner_settings']['testnet3']['cpu_percent'],10)
        self.assertEqual(new['miner_settings']['testnet4']['cpu_percent'],23)

    def test_legacy_fixed_address_is_never_copied_to_other_network(self):
        p=app_server.PREF_FILE
        p.write_text(json.dumps({'network':'testnet4','fixed_address':
            address_from_secret(1,'tempnet_fablous_2026'),'mining_target_mode':'address',
            'cpu_percent':20,'gpu_percent':25}),encoding='utf8')
        prefs=app_server._prefs_read()
        for net in ('mainnet','testnet3','testnet4','chipnet','tempnet_fablous_2026','regtest'):
            self.assertEqual(prefs['miner_settings'][net]['fixed_address'],'')
            self.assertEqual(prefs['miner_settings'][net]['mining_target_mode'],'wallet')

    def test_two_processes_at_once_and_independent_callbacks(self):
        s=self.service
        dest3=address_from_secret(1,'testnet3')
        dest4=address_from_secret(2,'testnet4')
        s.set_prefs({'network':'testnet3','mining_target_mode':'address',
                     'fixed_address':dest3,'cpu_percent':0,'gpu_percent':10})
        s.set_prefs({'network':'testnet4','mining_target_mode':'address',
                     'fixed_address':dest4,'cpu_percent':0,'gpu_percent':12})
        captures=[]
        def fake_start(ctl,settings):
            ctl.proc=FakeProcess()
            captures.append(settings)
            return []
        def fake_stop(ctl,*args,**kwargs):
            ctl.proc=None
        with patch.object(MinerController,'start',fake_start),patch.object(MinerController,'stop',fake_stop):
            s.start_miner({'network':'testnet3'})
            s.start_miner({'network':'testnet4'})
            state=s.state()
            self.assertEqual(state['active_mining_count'],2)
            self.assertTrue(state['mining_sessions']['testnet3']['mining'])
            self.assertTrue(state['mining_sessions']['testnet4']['mining'])
            self.assertEqual(set(x.network for x in captures),{'testnet3','testnet4'})
            self.assertEqual({x.network:x.reward_address for x in captures},
                             {'testnet3':dest3,'testnet4':dest4})
            # Volver a mostrar Mainnet no afecta a mineros activos
            self.assertEqual(s.state()['active_mining_count'],2)
            s.miner_line_for('testnet3','[mining] rate_total=1,000,000 H/s')
            s.miner_line_for('testnet4','[mining] rate_total=2,000,000 H/s')
            self.assertEqual(s.sessions['testnet3'].hashrate,1.0)
            self.assertEqual(s.sessions['testnet4'].hashrate,2.0)
            s.stop_miner('testnet3')
            # stop() runs in another thread; process state simulated only.
            import time
            for _ in range(50):
                if not s.sessions['testnet3'].mining.running():break
                time.sleep(.01)
            self.assertFalse(s.sessions['testnet3'].mining.running())
            self.assertTrue(s.sessions['testnet4'].mining.running())
            self.assertEqual(s.state()['active_mining_count'],1)
            s.stop_miner('testnet4')

    def test_log_names_cannot_collide_between_networks(self):
        for net in ('testnet3','testnet4','tempnet_fablous_2026'):
            name=f'cashminer.py_26-11-07_17h20m00s_{net}.log'
            self.assertIsNotNone(log_archive.LOG_NAME.fullmatch(name))
        self.assertIsNone(log_archive.LOG_NAME.fullmatch('cashminer.py_26-11-07_17h20m00s_../../x.log'))

    def test_log_listing_is_per_network_even_with_simultaneous_sessions(self):
        from unittest.mock import patch
        folder=Path(self.temp.name)/'logs'
        folder.mkdir()
        names=[
            'cashminer.py_26-11-07_17h00m00s_testnet3_a1b2c3.log',
            'cashminer.py_26-11-07_17h00m00s_testnet4_4d5e6f.log',
            'cashminer.py_26-11-07_17h00m00s_tempnet_fablous_2026_123abc.log',
        ]
        for n in names:(folder/n).write_text('test\n',encoding='utf8')
        with patch.object(log_archive,'logs_dir',lambda:folder):
            self.assertEqual([x['name'] for x in log_archive.sessions(network='testnet3')],[names[0]])
            self.assertEqual([x['name'] for x in log_archive.sessions(network='testnet4')],[names[1]])
            self.assertEqual([x['name'] for x in log_archive.sessions(network='tempnet_fablous_2026')],[names[2]])

    def test_wallet_selection_can_toggle_off_without_deleting(self):
        s=self.service
        s.switch_wallet_network('testnet4')
        s.select_wallet(None)
        self.assertIsNone(s.state()['selected_wallet'])

if __name__=='__main__':unittest.main()
