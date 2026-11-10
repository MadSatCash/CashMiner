"""Contrato de la v2.7.2: sin minar realmente ni utilizar secretos."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from cashminer.app import server as app_server
from cashminer.network import p2p
from cashminer.network.networks import NETWORKS
from cashminer.mining.bridge import MinerController


class WalletDefault272(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.temp.name})
        env.start();self.addCleanup(env.stop)
        pp=patch.object(app_server,'PREF_FILE',Path(self.temp.name)/'settings.json')
        pp.start();self.addCleanup(pp.stop)
        self.s=app_server.CashMinerService();self.addCleanup(self.s.stop_all)
        self.net='tempnet_fablous_2026'
        self.wallets=[{'id':'wA','address':'bchtest:exampleA','source':'v23','name':'A','network':self.net},
                      {'id':'wB','address':'bchtest:exampleB','source':'v23','name':'B','network':self.net}]
        chooser=patch.object(self.s,'miner_wallet_choices',side_effect=lambda net:self.wallets if net==self.net else [])
        chooser.start();self.addCleanup(chooser.stop)

    def test_auto_first_is_persisted_and_keeps_user_choice(self):
        self.assertEqual(self.s.mining_wallet_choice(self.net),'wA')
        self.assertEqual(app_server._prefs_read()['mining_wallet'][self.net],'wA')
        self.s.select_mining_wallet('wB',self.net)
        self.assertEqual(self.s.mining_wallet_choice(self.net),'wB')
        self.wallets=self.wallets[:1]  # simulando que se eliminó B
        self.assertEqual(self.s.mining_wallet_choice(self.net),'wA')
        self.wallets=[]
        self.assertIsNone(self.s.mining_wallet_choice(self.net))

    def test_start_automatically_chooses_first_without_modal(self):
        from cashminer.wallet.legacy_hd import address_from_secret
        addressA=address_from_secret(6,self.net)
        self.wallets[0]['address']=addressA
        started=[]
        def fake_start(controller,settings):
            started.append(settings)
            controller.proc=SimpleNamespace(poll=lambda: None)
            return []
        def fake_stop(controller,*args,**kwargs):controller.proc=None
        with patch.object(MinerController,'start',fake_start),patch.object(MinerController,'stop',fake_stop):
            self.s.start_miner({'network':self.net})
            self.assertEqual(started[0].reward_address,addressA)
            self.assertEqual(self.s.prefs['mining_wallet'][self.net],'wA')
            self.s.stop_all()


class PeerCheckpoint272(unittest.TestCase):
    def test_checkpoint_compatible_vs_incompatible_and_unknown(self):
        net=NETWORKS['tempnet_fablous_2026']
        header=bytearray(80)
        header[4:36]=bytes.fromhex(net.identity_locator)[::-1]
        payload=b'\x01'+bytes(header)+b'\x00'
        sock=SimpleNamespace(sendall=lambda data:None, gettimeout=lambda:1,
                             settimeout=lambda value:None)
        with patch.object(p2p,'recv_message',return_value=('headers',payload)):
            with patch.object(p2p,'sha256d',return_value=bytes.fromhex(net.identity_first_hash)[::-1]):
                self.assertEqual(p2p._verify_checkpoint(sock,net,1)[0],'compatible')
            with patch.object(p2p,'sha256d',return_value=b'\x01'*32):
                self.assertEqual(p2p._verify_checkpoint(sock,net,1)[0],'incompatible')
        with patch.object(p2p,'recv_message',return_value=('headers',b'\x00')):
            self.assertEqual(p2p._verify_checkpoint(sock,net,1)[0],'unverified')

    def test_network_anchor_matches_original_engine_constant(self):
        import importlib.util
        source=Path(__file__).resolve().parents[1]/'mining_engine'/'fablous'/'consensus.py'
        spec=importlib.util.spec_from_file_location('cashminer_fablous_for_test',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        net=NETWORKS['tempnet_fablous_2026']
        self.assertEqual(net.identity_locator,module.COMMON_HASH)
        self.assertEqual(net.identity_first_hash,module.FIRST_HASH)


class Interface272(unittest.TestCase):
    def test_first_section_is_reward_and_change_persists(self):
        html=(Path(__file__).resolve().parents[1]/'ui'/'index.html').read_text()
        block=html.split('function openMineConfig(){',1)[1].split('`,true);',1)[0]
        self.assertLess(block.find('Destino de recompensas'),block.find('Red y modalidad de minería'))
        self.assertIn("$('saveRewardDistribution').onclick",html)
        self.assertIn('id="miningRewardDetails"',html)
        self.assertNotIn('id="miningRewardDetails" open', html)
        self.assertIn('explorerCompatible:p.chain_compatible',html)
        self.assertIn('Peer Explorer · ${esc(current.explorer_state===',html)
        self.assertNotRegex(html, r'v2\.7\.1(?![0-9])')

    def test_browser_close_stops_service_even_without_button(self):
        import threading
        class Process:
            def __init__(self):self.closed=threading.Event()
            def poll(self):return 0 if self.closed.is_set() else None
            def wait(self,timeout=None):
                if not self.closed.wait(timeout):raise TimeoutError()
                return 0
            def terminate(self):self.closed.set()
        class Server:
            def __init__(self):
                self.signal=threading.Event();self.stopped=threading.Event()
                self.service=SimpleNamespace(stop_all=self.stopped.set)
            def serve_forever(self,**kwargs):self.signal.wait(3)
            def shutdown(self):self.signal.set()
        browser=Process();server=Server()
        def simulate_user_close():browser.closed.set()
        with patch.object(app_server,'_start_managed_browser',return_value=(browser,None)):
            t=threading.Timer(.05,simulate_user_close);t.start()
            app_server._run_managed_browser(server,'http://127.0.0.1:8888/')
        self.assertTrue(server.stopped.is_set())
        self.assertTrue(server.signal.is_set())

if __name__=='__main__':unittest.main()
