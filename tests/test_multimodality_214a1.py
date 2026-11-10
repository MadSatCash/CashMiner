"""v2.16: offline modality compatibility and fail-closed reference selection."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cashminer.mining.bridge import (
    MINING_MODES, DEFAULT_MODES, DEFAULT_TIP_SOURCES, P2P_TIP_SOURCES,
    MiningSettings, MinerController,
)
from cashminer.app import server as app_server
from cashminer.wallet.legacy_hd import address_from_secret

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'mining_engine'))
import miner as engine


class MultiModal214(unittest.TestCase):
    def test_native_default_preserves_modes_and_assisted_option(self):
        for net in ('testnet3','testnet4','chipnet'):
            self.assertEqual(P2P_TIP_SOURCES[net], ('native','electrum_assisted'))
            self.assertEqual(DEFAULT_MODES[net], 'p2p-tip')
        self.assertEqual(P2P_TIP_SOURCES['tempnet_fablous_2026'], ('native',))
        self.assertEqual(DEFAULT_MODES['tempnet_fablous_2026'],'p2p-tip')
        self.assertEqual(P2P_TIP_SOURCES['mainnet'], ('native','electrum_assisted'))
        self.assertEqual(DEFAULT_MODES['mainnet'], 'p2p-tip')
        self.assertIn('p2p-tip', MINING_MODES['mainnet'])
        self.assertEqual(P2P_TIP_SOURCES['regtest'], ('native',))
        self.assertEqual(DEFAULT_MODES['regtest'],'rpc')
        self.assertIn('p2p-tip',MINING_MODES['regtest'])

    def test_rpc_stratum_can_be_selected_for_any_network(self):
        for net in MINING_MODES:
            self.assertIn('rpc',MINING_MODES[net])
            self.assertIn('pool',MINING_MODES[net])
            addr=address_from_secret(1,net)
            MiningSettings(net,addr,mode='rpc',gpu_percent=0,
                           rpc_url='http://127.0.0.1:18443').validate()
            MiningSettings(net,'',mode='pool',gpu_percent=0,
                           pool_url='stratum+ssl://pool.example:3333',pool_user='worker').validate()

    def test_tip_source_never_chooses_an_unimplemented_provider(self):
        for net, sources in P2P_TIP_SOURCES.items():
            if sources:
                MiningSettings(net,address_from_secret(1,net),mode='p2p-tip',gpu_percent=0,
                               tip_source=sources[0]).validate()
                with self.assertRaises(ValueError):
                    MiningSettings(net,address_from_secret(1,net),mode='p2p-tip',gpu_percent=0,
                                   tip_source='unsupported').validate()
            else:
                with self.assertRaises(ValueError):
                    MiningSettings(net,address_from_secret(1,net),mode='p2p-tip',gpu_percent=0).validate()
        with self.assertRaises(ValueError):
            MiningSettings('testnet3',address_from_secret(1,'testnet3'),mode='rpc',gpu_percent=0,
                           tip_source='native',rpc_url='http://127.0.0.1:18443').validate()

    def test_settings_persist_each_chain_tip_reference_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{'CASHMINER_DATA_DIR':tmp}), patch.object(app_server,'PREF_FILE',Path(tmp)/'settings.json'):
                svc=app_server.CashMinerService()
                try:
                    # Vista independiente de testnet3
                    self.assertEqual(svc.state('testnet3')['mining_tip_sources'],['native','electrum_assisted'])
                    svc.configure_mining_connection({'network':'testnet3','mode':'p2p-tip',
                                                     'tip_source':'electrum_assisted'})
                    svc.configure_mining_connection({'network':'testnet3','mode':'p2p-tip',
                                                     'tip_source':'native'})
                    # Vista independiente de tempnet
                    self.assertEqual(svc.state('tempnet_fablous_2026')['mining_tip_source'],'native')
                    svc.configure_mining_connection({'network':'tempnet_fablous_2026','mode':'pool',
                        'pool_url':'stratum+ssl://pool.example:3333','pool_user':'account.worker',
                        'pool_password':'DO-NOT-STORE-THIS'})
                    self.assertTrue(svc.state('tempnet_fablous_2026')['mining_connection_ready'])
                    self.assertNotIn('DO-NOT-STORE-THIS',(Path(tmp)/'settings.json').read_text())
                    self.assertEqual(svc.prefs['miner_settings']['testnet3']['tip_source'],'native')
                    self.assertEqual(svc.prefs['miner_settings']['tempnet_fablous_2026']['tip_source'],'native')
                finally:
                    svc.stop_all()

    def test_bridge_passes_source_to_engine_only_for_p2p(self):
        class FakeProc:
            def __init__(self):self.stdout=io.StringIO('')
            def poll(self):return 0
            def wait(self):return 0
        samples=[
            MiningSettings('chipnet',address_from_secret(1,'chipnet'),mode='p2p-tip',
                           tip_source='electrum_assisted',gpu_percent=0),
            MiningSettings('tempnet_fablous_2026',address_from_secret(1,'tempnet_fablous_2026'),
                           mode='p2p-tip',tip_source='native',gpu_percent=0),
            MiningSettings('regtest','',mode='pool',pool_url='stratum+tcp://127.0.0.1:3333',
                           pool_user='test.worker',gpu_percent=0),
        ]
        for case in samples:
            with self.subTest(case=case.network),tempfile.TemporaryDirectory() as td:
                captured=[]
                def fake_popen(args,**kw):
                    captured.append((args,kw['env']))
                    return FakeProc()
                with patch.dict(os.environ,{'CASHMINER_DATA_DIR':td}),\
                     patch('cashminer.mining.bridge.subprocess.Popen',side_effect=fake_popen):
                    ctl=MinerController(lambda _:None,lambda *_:None)
                    ctl.start(case);ctl.wait_for_log_close()
                args,env=captured[0]
                self.assertEqual(args[args.index('--miner-mode')+1],case.mode)
                expected=case.tip_source or DEFAULT_TIP_SOURCES[case.network]
                if case.mode=='p2p-tip':
                    self.assertEqual(env['CASHMINER2_P2P_TIP_SOURCE'],expected)
                else:
                    self.assertNotIn('CASHMINER2_P2P_TIP_SOURCE',env)

    def test_rpc_identity_check_each_network_and_refuse_wrong_chain(self):
        for net,(height,expected) in engine.RPC_KNOWN_ANCHORS.items():
            with self.subTest(net=net):
                rpc=Mock();rpc.call.return_value=expected
                with patch.object(engine,'log'):
                    engine.verify_rpc_chain(rpc,net)
                rpc.call.assert_called_once_with('getblockhash',[height])
                rpc.call.return_value='00'*32
                with self.assertRaisesRegex(RuntimeError,'incompatible'):
                    engine.verify_rpc_chain(rpc,net)
        rpc=Mock();rpc.call.return_value={'chain':'regtest'}
        with patch.object(engine,'log'):
            engine.verify_rpc_chain(rpc,'regtest')
        rpc.call.return_value={'chain':'main'}
        with self.assertRaisesRegex(RuntimeError,'no corresponde'):
            engine.verify_rpc_chain(rpc,'regtest')

    def test_rpc_solution_goes_to_submitblock_on_mainnet_and_tempnet(self):
        for net in ('mainnet','tempnet'):
            with self.subTest(net=net):
                miner=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
                miner.false_positive_total=0
                miner.false_positive_by_height={}
                miner.deep_debug_false_positive=False
                miner.miner_address='public'
                miner.script_pubkey=b'\x51'
                miner.rpc=Mock()
                miner.rpc.call.return_value=None
                with patch.object(engine,'NETWORK',net),patch.object(engine,'MINER_MODE','rpc'),\
                     patch.object(engine,'sha256d',return_value=b'\x00'*32),\
                     patch.object(engine,'bits_to_target',return_value=2**256-1),\
                     patch.object(engine,'save_found_block',return_value='test-block'),\
                     patch.object(engine,'build_full_block_hex',return_value='00'),\
                     patch.object(engine,'broadcast_block_hex',return_value=[]),\
                     patch.object(engine,'log'),patch.object(engine,'collect_peers_from_seeds',return_value=[]):
                    result=miner.handle_found_block(
                        height=1,prev_hash='00'*32,bits_hex='207fffff',version=4,
                        ntime=1,coinbase_value=1,workid=None,merkle_root_le=b'\x00'*32,
                        coinbase_tx=b'\x00',other_txs_hex=[],header=b'\x00'*80,nonce=1,
                        extra_nonce=0,block_hash_le=b'\x00'*32)
                self.assertEqual(result,'found')
                miner.rpc.call.assert_called_once_with('submitblock',['00'])

    def test_ui_only_shows_tip_source_when_p2p_and_no_fake_mainnet(self):
        html=(ROOT/'ui/index.html').read_text()
        self.assertIn('miningTipSourceFields',html)
        self.assertIn("mode!=='p2p-tip'",html)
        self.assertIn('P2P nativo es experimental y no requiere Electrum',html)
        self.assertIn('Electrum asistido sigue disponible',html)

if __name__=='__main__':
    unittest.main()

