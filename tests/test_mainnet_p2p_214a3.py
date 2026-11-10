"""Deterministic Mainnet assisted-P2P safeguards, no live networking."""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.mining.bridge import MINING_MODES, P2P_TIP_SOURCES, DEFAULT_MODES, MiningSettings
from cashminer.wallet.legacy_hd import address_from_secret
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine

class MainnetP2PSafeguards(unittest.TestCase):
    def test_mainnet_mode_and_reference_separation(self):
        self.assertEqual(DEFAULT_MODES['mainnet'],'p2p-tip')
        self.assertEqual(P2P_TIP_SOURCES['mainnet'],('native','electrum_assisted'))
        self.assertIn('rpc',MINING_MODES['mainnet'])
        self.assertIn('pool',MINING_MODES['mainnet'])
        addr=address_from_secret(1,'mainnet')
        MiningSettings('mainnet',addr,mode='p2p-tip',tip_source='electrum_assisted').validate()
        MiningSettings('mainnet',addr,mode='p2p-tip',tip_source='native').validate()
        with self.assertRaises(ValueError):
            MiningSettings('mainnet',addr,mode='p2p-tip',tip_source='unsupported').validate()

    def test_mainnet_asert_parameters_no_testnet_min_diff(self):
        self.assertEqual(engine.MAINNET_ASERT_ANCHOR_HEIGHT,661647)
        self.assertEqual(engine.MAINNET_ASERT_HALFLIFE,172800)
        self.assertEqual(engine.MAINNET_ASERT_ANCHOR_BITS,402971390)
        h=engine.MAINNET_ASERT_ANCHOR_HEIGHT
        t=engine.MAINNET_ASERT_ANCHOR_PARENT_TIME+600
        anchor=f'{engine.MAINNET_ASERT_ANCHOR_BITS:08x}'
        # A 600-second offset with height=anchor recovers the same target.
        self.assertEqual(engine.compute_next_bits_mainnet(h,t,t+10),anchor)
        self.assertEqual(engine.compute_next_bits_mainnet(h,t,t+1201),anchor)
        with patch.object(engine,'NETWORK','mainnet'):
            self.assertEqual(engine.compute_next_bits_for_network(h,t,t+1800),anchor)
        with self.assertRaises(ValueError):
            engine.compute_next_bits_mainnet(h-1,t,t)

    def test_mainnet_does_not_trust_longer_unvalidated_peer_headers(self):
        electrum_tip=b"e"*32
        advanced=b"a"*32
        with patch.object(engine,'NETWORK','mainnet'),\
             patch.object(engine,'load_testnet_p2p_tip_peers_from_db',return_value=['192.0.2.1:8333']),\
             patch.object(engine,'_check_testnet3_peer_against_electrum_tip',return_value={
                 'status':'compatible','detail':{'peer':'192.0.2.1:8333','headers_count':4,
                 'tip_time':1234567,'tip_height':900004,'tip_hash_le':advanced,
                 'tip_hash_hex':advanced[::-1].hex(),'tip_bits_hex':'1a123456'}}):
            r=engine.fetch_testnet3_tip_from_peers_using_electrum_tip(electrum_tip,900000)
        self.assertEqual(r['tip_hash_le'],electrum_tip)
        self.assertEqual(r['tip_height'],900000)
        self.assertIsNone(r['tip_bits_hex'])
        self.assertEqual(len(r['compatible_peers']),1)

    def test_wrong_chain_electrum_rejected_before_tip(self):
        with patch.object(engine,'NETWORK','mainnet'),\
             patch.object(engine,'mining_electrum_candidates',return_value=[('host.example',50002)]),\
             patch.object(engine,'electrum_request',return_value={'genesis_hash':'00'*32}),\
             patch.object(engine,'log'),\
             patch.dict(engine.ELECTRUM_BAD_UNTIL,{'mainnet':{}},clear=True):
            with self.assertRaisesRegex(RuntimeError,'Sin servidor Electrum válido'):
                engine.fetch_testnet_tip_from_electrum()

    def test_mainnet_has_fork_and_recent_checkpoints(self):
        self.assertEqual(engine.MAINNET_BCH_FORK_CHECKPOINT[0],478559)
        # This mainnet hash is sourced independently of miner.py.
        self.assertEqual(engine.MAINNET_RECENT_CHECKPOINT,
                         (924992,'000000000000000000364d1c154cbbe17c7b428902de7cc320f9ac9d61d2df37'))
        # Testnet3 height 900000 must NOT be confused with BCH Mainnet.
        self.assertNotEqual(engine.MAINNET_RECENT_CHECKPOINT[1],
                            '0000000000356f8d8924556e765b7a94aaebc6b5c8685dcfa2b1ee8b41acd89b')
        self.assertEqual(engine.ELECTRUM_FORK_CHECKPOINTS['mainnet'],engine.MAINNET_RECENT_CHECKPOINT)
        self.assertNotEqual(engine.MAINNET_BCH_FORK_CHECKPOINT[1],engine.MAINNET_RECENT_CHECKPOINT[1])

if __name__=='__main__':unittest.main()

class MainnetPinnedElectrum(unittest.TestCase):
    def _responses(self,bad_recent=False):
        now=int(time.time())
        tip=bytearray(80)
        tip[68:72]=now.to_bytes(4,'little')
        tip[72:76]=(0x1d00ffff).to_bytes(4,'little')
        raw_tip=bytes(tip)
        fork=b'\x04'*80
        recent=b'\x05'*80
        anchor=b'\x06'*80
        chk_fork=bytes.fromhex(engine.MAINNET_BCH_FORK_CHECKPOINT[1])[::-1]
        chk_recent=bytes.fromhex(engine.MAINNET_RECENT_CHECKPOINT[1])[::-1]
        mapping={fork:chk_fork,recent:(b'\x01'*32 if bad_recent else chk_recent),raw_tip:b'\x00'*32,anchor:b'\x09'*32}
        def fake_rpc(host,port,method,params,**kwargs):
            if method=='server.features':return {'genesis_hash':engine.TESTNET_ELECTRUM_GENESIS['mainnet']}
            if method=='blockchain.headers.subscribe':return {'height':925050,'hex':raw_tip.hex()}
            if method=='blockchain.block.header':
                return {478559:fork.hex(),924992:recent.hex(),925040:anchor.hex()}[params[0]]
            raise AssertionError(method)
        def fake_sha(raw):return mapping[raw]
        return fake_rpc,fake_sha

    def test_two_bch_history_anchors_and_tip_pow_required(self):
        rpc,sha=self._responses()
        with patch.object(engine,'NETWORK','mainnet'),\
             patch.object(engine,'mining_electrum_candidates',return_value=[('cash.example',50002)]),\
             patch.object(engine,'electrum_request',side_effect=rpc),\
             patch.object(engine,'sha256d',side_effect=sha),\
             patch.object(engine,'log'),\
             patch.dict(engine.ELECTRUM_BAD_UNTIL,{'mainnet':{}},clear=True),\
             patch.dict(engine.ELECTRUM_ACTIVE_ENDPOINT,{},clear=True):
            result=engine.fetch_testnet_tip_from_electrum()
            self.assertEqual(result['tip_height'],925050)
            self.assertEqual(result['electrum_host'],'cash.example')
            self.assertEqual(result['anchor_height'],925040)

    def test_recent_checkpoint_mismatch_aborts_before_hashing(self):
        rpc,sha=self._responses(bad_recent=True)
        with patch.object(engine,'NETWORK','mainnet'),\
             patch.object(engine,'mining_electrum_candidates',return_value=[('cash.example',50002)]),\
             patch.object(engine,'electrum_request',side_effect=rpc),\
             patch.object(engine,'sha256d',side_effect=sha),\
             patch.object(engine,'log'),\
             patch.dict(engine.ELECTRUM_BAD_UNTIL,{'mainnet':{}},clear=True),\
             patch.dict(engine.ELECTRUM_ACTIVE_ENDPOINT,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'Sin servidor Electrum válido'):
                engine.fetch_testnet_tip_from_electrum()
