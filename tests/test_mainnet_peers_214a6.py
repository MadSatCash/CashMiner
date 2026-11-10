"""Mainnet mining bridge sends curated SQLite peers, not only DNS seeds."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.mining import bridge
from cashminer.wallet.legacy_hd import address_from_secret


class MainnetPeerSelection(unittest.TestCase):
    def _launch(self, mode, peers=(), *, custom=(), preferred=''):
        class FakeProc:
            def __init__(self):
                self.stdout=io.StringIO('')
            def poll(self): return 0
            def wait(self): return 0
        with tempfile.TemporaryDirectory() as td:
            seen=[]
            def fake_popen(argv, **kw):
                seen.append((argv,kw['env']))
                return FakeProc()
            params=dict(network='mainnet',reward_address=address_from_secret(7,'mainnet'),
                        mode=mode,cpu_percent=25,gpu_percent=0,peers=tuple(peers),
                        tip_source='electrum_assisted' if mode=='p2p-tip' else '',
                        electrum_custom=tuple(custom),electrum_preferred=preferred)
            if mode=='rpc':
                params['rpc_url']='http://127.0.0.1:8332'
            if mode=='pool':
                params['pool_url']='stratum+tcp://127.0.0.1:3333'
                params['pool_user']='worker'
            with patch.dict(os.environ,{'CASHMINER_DATA_DIR':td},clear=False), \
                 patch.object(bridge,'prepare_runtime',return_value=(Path(td),[])), \
                 patch.object(bridge.subprocess,'Popen',side_effect=fake_popen):
                controller=bridge.MinerController(lambda _:None,lambda *_:None)
                controller.start(bridge.MiningSettings(**params))
                controller.wait_for_log_close()
            self.assertEqual(len(seen),1)
            return seen[0]

    def test_mainnet_p2p_prefers_curated_peers_and_electrum(self):
        peers=('198.51.100.10:8333','[2001:db8::4]:8333')
        extra='custom.example.org:50002'
        argv,env=self._launch('p2p-tip',peers,custom=(extra,),preferred=extra)
        self.assertEqual(env['CASHMINER2_SQLITE_PEERS'],'1')
        self.assertEqual(env['CASHMINER2_P2P_TIP_SOURCE'],'electrum_assisted')
        i=argv.index('--broadcast-peer')
        self.assertEqual(argv[i+1],peers[0])
        self.assertEqual(argv[i+3],peers[1])
        electrum=json.loads(env['CASHMINER2_ELECTRUM_ENDPOINTS'])
        self.assertEqual(electrum[0],extra)
        self.assertEqual(electrum[1],'bch.imaginary.cash:50002')
        self.assertEqual(electrum[2],'bch.loping.net:50002')
        self.assertNotIn('BCH_PEER_DB_DSN',env)

    def test_empty_mainnet_peers_falls_back_to_seeds(self):
        argv,env=self._launch('p2p-tip')
        self.assertNotIn('CASHMINER2_SQLITE_PEERS',env)
        self.assertNotIn('--broadcast-peer',argv)
        self.assertEqual(json.loads(env['CASHMINER2_ELECTRUM_ENDPOINTS'])[0],
                         'bch.imaginary.cash:50002')

    def test_other_modalities_do_not_inherit_p2p_settings(self):
        for mode in ('rpc','pool'):
            with self.subTest(mode=mode):
                argv,env=self._launch(mode,('198.51.100.10:8333',))
                self.assertNotIn('CASHMINER2_SQLITE_PEERS',env)
                self.assertNotIn('CASHMINER2_ELECTRUM_ENDPOINTS',env)
                self.assertNotIn('CASHMINER2_P2P_TIP_SOURCE',env)

    def test_mainnet_engine_uses_passed_peers_but_keeps_chain_checks(self):
        import sys
        engine_path=str(Path(__file__).resolve().parents[1]/'mining_engine')
        if engine_path not in sys.path:sys.path.insert(0,engine_path)
        import miner as engine
        with patch.object(engine,'NETWORK','mainnet'), \
             patch.object(engine,'BROADCAST_PEERS',['198.51.100.10:8333']), \
             patch.dict(os.environ,{'CASHMINER2_SQLITE_PEERS':'1'},clear=False):
            self.assertEqual(engine.load_testnet_p2p_tip_peers_from_db(5),
                             ['198.51.100.10:8333'])
            self.assertEqual(engine.TESTNET_CFG['mainnet']['port'],8333)


if __name__=='__main__':unittest.main()
