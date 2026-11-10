"""Native checkpoint/PoW/DAA/work regressions; never contacts a public peer."""
import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine
import native_headers as native
from fablous.consensus import parse_header,bits_to_target
from cashminer.mining.bridge import MiningSettings,P2P_TIP_SOURCES,MINING_MODES
from cashminer.wallet.legacy_hd import address_from_secret


def header(parent,when,bits=0x207fffff):
    prefix=struct.pack('<I',0x20000000)+bytes.fromhex(parent)[::-1]+bytes(32)+struct.pack('<II',when,bits)
    target=bits_to_target(bits)
    for nonce in range(100000):
        raw=prefix+struct.pack('<I',nonce)
        digest=hashlib.sha256(hashlib.sha256(raw).digest()).digest()
        if int.from_bytes(digest,'little')<=target:return raw
    raise AssertionError('easy PoW fixture did not solve')


class NativeHeaders216(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def client(self,expected=None,**kwargs):
        return native.NativeHeaderClient('regtest',['127.0.0.1:18444'],expected or (lambda *args:'207fffff'),**kwargs)

    def chain(self,count,parent=None,start=1300000000,bits=0x207fffff):
        parent=parent or native.CHECKPOINTS['regtest'][1];out=[]
        for i in range(count):
            raw=header(parent,start+i,bits);out.append(raw);parent=parse_header(raw)['hash']
        return out

    def sync_batch(self,client,headers,max_rounds=500):
        broadcaster=Mock();broadcaster.connect.return_value=Mock()
        with patch.object(native,'BlockBroadcaster',return_value=broadcaster), \
             patch.object(client,'_read_headers',return_value=headers):
            return client.sync_peer('127.0.0.1:18444',max_rounds=max_rounds)

    def test_fixed_contexts_and_real_post_checkpoint_vectors_on_four_networks(self):
        vectors=json.loads((ROOT/'tests/native_header_vectors_216.json').read_text())
        functions={'mainnet':engine.compute_next_bits_mainnet,'testnet3':engine.compute_next_bits_testnet3,
                   'testnet4':engine.compute_next_bits_testnet4,'chipnet':engine.compute_next_bits_testnet4}
        for net,fn in functions.items():
            with self.subTest(network=net):
                client=native.NativeHeaderClient(net,[],fn)
                self.assertEqual(client.tip['tip_hash_hex'],native.CHECKPOINTS[net][1])
                self.assertEqual(len(client.context),11)
                data=bytes.fromhex(vectors[net])
                for i in range(0,len(data),80):client._append(client.chain,data[i:i+80])
                self.assertEqual(client.tip['tip_height'],native.CHECKPOINTS[net][0]+3)

    def test_regtest_genesis_and_next_difficulty_and_subsidy(self):
        client=self.client();self.assertEqual(client.tip['tip_height'],0)
        self.assertEqual(client.tip['tip_hash_hex'],native.CHECKPOINTS['regtest'][1])
        with patch.object(engine,'NETWORK','regtest'):
            self.assertEqual(engine.compute_next_bits_for_network(150,1,99999),'207fffff')
            self.assertEqual(engine.get_block_subsidy_sats(149),5000000000)
            self.assertEqual(engine.get_block_subsidy_sats(150),2500000000)

    def test_invalid_pow_and_target_are_rejected(self):
        client=self.client()
        for raw in (bytes(80),self.chain(1)[0][:72]+struct.pack('<I',0x2100ffff)+bytes(4)):
            with self.assertRaises(ValueError):client._pow(raw)

    def test_invalid_link_difficulty_mtp_and_future_time_are_rejected(self):
        client=self.client()
        bad=[header('11'*32,1300000000),header(client.checkpoint,1300000000,0x200fffff),
             header(client.checkpoint,client.tip['time']),header(client.checkpoint,int(time.time())+7300)]
        for raw in bad:
            with self.subTest(raw=raw.hex()),self.assertRaises(ValueError):client._append([],raw)

    def test_sync_and_cache_revalidate_before_use(self):
        path=self.root/'regtest.bin';client=self.client(cache_path=path)
        headers=self.chain(4);result=self.sync_batch(client,headers)
        self.assertEqual(result['height'],4);self.assertGreater(result['work'],0)
        client.save_cache();restored=self.client(cache_path=path)
        self.assertEqual(restored.tip['tip_hash_hex'],client.tip['tip_hash_hex'])
        self.assertEqual(restored.work,client.work)
        path.write_bytes(path.read_bytes()[:-1]);restored=self.client(cache_path=path)
        self.assertEqual(restored.chain,[])

    def test_work_wins_over_height_for_a_verified_fork(self):
        # Synthetic easy-work network, to exercise selection independently of DAA.
        client=self.client(expected=lambda h,p,t:'200fffff' if t>=1400000000 else '207fffff')
        self.sync_batch(client,self.chain(3));old=client.work
        self.sync_batch(client,self.chain(2,start=1400000000,bits=0x200fffff))
        self.assertEqual(client.tip['tip_height'],2);self.assertGreater(client.work,old)

    def test_equal_or_less_work_does_not_replace_best_chain(self):
        client=self.client();self.sync_batch(client,self.chain(3));old=client.tip['tip_hash_hex']
        self.sync_batch(client,self.chain(2,start=1400000000))
        self.assertEqual(client.tip['tip_hash_hex'],old)

    def test_failed_validation_does_not_publish_partial_chain(self):
        client=self.client();headers=self.chain(3);headers[-1]=header('22'*32,1400000000)
        with self.assertRaises(ValueError):self.sync_batch(client,headers)
        self.assertEqual(client.chain,[]);self.assertEqual(client.work,0)

    def test_round_limit_never_publishes_incomplete_tip(self):
        client=self.client()
        with self.assertRaisesRegex(RuntimeError,'incompleta'):self.sync_batch(client,self.chain(2000),max_rounds=1)
        self.assertEqual(client.chain,[])

    def test_wrong_network_checkpoint_is_rejected_before_following_headers(self):
        client=native.NativeHeaderClient('mainnet',[],engine.compute_next_bits_mainnet)
        broadcaster=Mock();broadcaster.connect.return_value=Mock()
        with patch.object(native,'BlockBroadcaster',return_value=broadcaster), \
             patch.object(client,'_read_headers',return_value=[native.GENESIS_REGTEST]):
            with self.assertRaisesRegex(ValueError,'checkpoint'):client.sync_peer('127.0.0.1:18444')
        self.assertEqual(client.chain,[])
        self.assertTrue(any(call.args[1]=='chain_incompatible' for call in broadcaster._observe.call_args_list))

    def test_no_peers_never_uses_unconfirmed_cached_tip(self):
        client=self.client();client.peers=()
        with self.assertRaisesRegex(RuntimeError,'Sin referencia'):client.sync()

    def test_native_mode_exposed_with_assisted_fallback_and_regtest(self):
        for net in MINING_MODES:
            with self.subTest(network=net):
                self.assertIn('p2p-tip',MINING_MODES[net]);self.assertIn('native',P2P_TIP_SOURCES[net])
                MiningSettings(net,address_from_secret(1,net),mode='p2p-tip',tip_source='native',gpu_percent=0).validate()
        for net in ('mainnet','testnet3','testnet4','chipnet'):self.assertIn('electrum_assisted',P2P_TIP_SOURCES[net])

    def test_native_template_reuses_backend_without_rpc_or_electrum(self):
        solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        client=self.client();tip=client.tip;tip['peers_ok']=['127.0.0.1:18444']
        solo.native_client=Mock();solo.native_client.sync.return_value=tip
        solo._tempnet_watch_lock=threading.Lock()
        solo.invalidator=SimpleNamespace(invalidate_event=threading.Event())
        solo.cuda_scanner=None;solo.c_scanner=None
        with patch.object(engine,'NETWORK','regtest'),patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'1'}), \
             patch.object(solo,'_ensure_native_tipwatch',create=True), \
             patch.object(solo,'mine_template_multiprocess',create=True,return_value=True) as mine, \
             patch.object(engine.RPCClient,'call',side_effect=AssertionError('RPC')), \
             patch.object(engine,'fetch_testnet_tip_from_electrum',side_effect=AssertionError('Electrum')):
            self.assertTrue(solo.mine_native_p2p_tip())
        values=mine.call_args.kwargs
        self.assertEqual(values['height'],1);self.assertEqual(values['prev_hash'],native.CHECKPOINTS['regtest'][1])
        self.assertEqual(values['bits_hex'],'207fffff');self.assertEqual(values['coinbase_value'],5000000000)

    def test_native_quorum_is_preserved_and_single_peer_requires_consent(self):
        solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        tip={'peers_ok':['1.2.3.4:8333']}
        with patch.object(engine,'NETWORK','mainnet'),patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'2'}):
            with self.assertRaises(RuntimeError):solo._native_require_peers(tip)
        with patch.object(engine,'NETWORK','mainnet'),patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'1','CASHMINER2_SINGLE_PEER_CONSENT':'0'}):
            with self.assertRaises(RuntimeError):solo._native_require_peers(tip)
        with patch.object(engine,'NETWORK','mainnet'),patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'1','CASHMINER2_SINGLE_PEER_CONSENT':'1'}):solo._native_require_peers(tip)

    def test_opencl_only_native_work_reaches_existing_gpu_backend(self):
        solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        client=self.client();tip=client.tip;tip['peers_ok']=['127.0.0.1:18444']
        solo.native_client=Mock();solo.native_client.sync.return_value=tip
        solo._tempnet_watch_lock=threading.Lock()
        solo.invalidator=SimpleNamespace(invalidate_event=threading.Event())
        solo.cuda_scanner=None;solo.c_scanner=None;solo.opencl_scanner=SimpleNamespace(available=True)
        with patch.object(engine,'NETWORK','regtest'),patch.object(engine,'GPU_ENABLED',True), \
             patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'1'}), \
             patch.object(solo,'_ensure_native_tipwatch'), \
             patch.object(solo,'mine_template_hybrid_cpu_cuda',return_value=True) as gpu:
            self.assertTrue(solo.mine_native_p2p_tip())
        self.assertEqual(gpu.call_args.kwargs['bits_hex'],'207fffff')

    def test_opencl_only_tempnet_work_reaches_existing_gpu_backend(self):
        solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        tip=dict(tip_height=350000,tip_hash_hex='11'*32,tip_time=1794300000,
            version=0x20000000,peers_ok=['1.2.3.4:48333','5.6.7.8:48333'])
        solo.tempnet_client=Mock();solo.tempnet_client.sync.return_value=tip
        solo._tempnet_watch_lock=threading.Lock()
        solo.invalidator=SimpleNamespace(invalidate_event=threading.Event())
        solo.miner_address='bchtest:public-test-fixture';solo.script_pubkey=b'\x51'
        solo.cuda_scanner=None;solo.c_scanner=None;solo.opencl_scanner=SimpleNamespace(available=True)
        with patch.object(engine,'NETWORK','tempnet'),patch.object(engine,'GPU_ENABLED',True), \
             patch.object(engine.time,'time',return_value=1794300001), \
             patch.dict(os.environ,{'CASHMINER2_MIN_PEERS':'2'}), \
             patch.object(solo,'_ensure_tempnet_tipwatch'), \
             patch.object(solo,'mine_template_hybrid_cpu_cuda',return_value=True) as gpu:
            self.assertTrue(solo.mine_tempnet_p2p_tip())
        self.assertEqual(gpu.call_args.kwargs['height'],350001)


if __name__=='__main__':unittest.main()
