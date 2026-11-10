"""v2.12: distribución coinbase y configuración; sin RPC ni bloques reales."""
from __future__ import annotations

import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.mining.rewards import (TOTAL_UNITS, percentage_units,validate_destinations,
                                      validate_saved_destinations)
from cashminer.wallet.legacy_hd import address_from_secret,validate_cashaddr
from cashminer.mining.bridge import MiningSettings

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine


class RewardMath212(unittest.TestCase):
    def test_largest_remainder_example(self):
        splits=[(b'a',500000),(b'b',300000),(b'c',200000)]
        self.assertEqual(engine.allocate_coinbase_outputs(101,splits),[(51,b'a'),(30,b'b'),(20,b'c')])
        self.assertEqual(engine.allocate_coinbase_outputs(312500031,splits),[(156250016,b'a'),(93750009,b'b'),(62500006,b'c')])

    def test_tie_order_and_never_zero(self):
        self.assertEqual(engine.allocate_coinbase_outputs(3,[(b'a',500000),(b'b',500000)]),[(2,b'a'),(1,b'b')])
        with self.assertRaisesRegex(ValueError,'menos de 1'):
            engine.allocate_coinbase_outputs(1,[(b'a',500000),(b'b',500000)])

    def test_large_values_still_exact(self):
        splits=[(bytes([i+1]),1) for i in range(15)]+[(b'last',999985)]
        outputs=engine.allocate_coinbase_outputs(12_500_000_000,splits)
        self.assertEqual(sum(v for v,_ in outputs),12_500_000_000)
        self.assertEqual(len(outputs),16)
        self.assertTrue(all(v>0 for v,_ in outputs))

    def test_rejects_corrupted_plans(self):
        for splits in ([], [(b'x',0)],[(b'x',1_000_001)],[(b'x',1_000_000)]*17,
                       [(b'',1_000_000)],[(b'x',True)],[(b'x',500000),(b'y',490000)]):
            with self.subTest(splits=splits),self.assertRaises(ValueError):
                engine.allocate_coinbase_outputs(500_000_000,splits)

    def test_transaction_serialization_multiple_outputs(self):
        addr=[address_from_secret(k,'regtest') for k in (1,2,3)]
        scripts=[engine.cashaddr_to_scriptpubkey(a) for a in addr]
        amounts=engine.allocate_coinbase_outputs(101,list(zip(scripts,(500000,300000,200000))))
        raw=engine.build_coinbase_tx(200,4,101,scripts[0],outputs=amounts)
        stream=io.BytesIO(raw)
        self.assertEqual(struct.unpack('<I',stream.read(4))[0],1)
        self.assertEqual(engine._read_varint(stream),1)
        stream.read(36)
        signature=stream.read(engine._read_varint(stream))
        self.assertEqual(signature[0],2)  # height 200 serialized via BIP34 push
        stream.read(4)  # sequence
        self.assertEqual(engine._read_varint(stream),3)
        found=[]
        for _ in range(3):
            amount=struct.unpack('<Q',stream.read(8))[0]
            script=stream.read(engine._read_varint(stream))
            found.append((amount,script))
        self.assertEqual(found,amounts)
        self.assertEqual(stream.read(4),b'\x00'*4)
        self.assertEqual(stream.read(),b'')
        single=engine.build_coinbase_tx(200,4,101,scripts[0])
        self.assertEqual(single[4],1)
        self.assertEqual(engine._read_varint(io.BytesIO(single[4:5])),1)
        self.assertNotEqual(engine.sha256d(raw),engine.sha256d(single))

    def test_percent_parser_never_uses_floats(self):
        for text, expected in [('100',TOTAL_UNITS),('0.0001',1),('33.3333',333333),('0.1',1000)]:
            self.assertEqual(percentage_units(text),expected)
        for invalid in (0,50.0,'','0','0.00001','33,3333','-5','100.0001','1e2',' 10 '):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):percentage_units(invalid)


class RewardSettings212(unittest.TestCase):
    def setUp(self):
        self.network='testnet3'
        self.addresses=[address_from_secret(k,self.network) for k in (1,2,3)]
        self.map={'first':self.addresses[0],'second':self.addresses[1]}
        self.resolve=lambda wid,net:(self.map[wid],'')

    def test_wallet_address_resolved_by_server_not_supplied_by_browser(self):
        plan=validate_destinations([
            {'type':'wallet','wallet_id':'first','address':self.addresses[2],'percent':'50'},
            {'type':'address','address':self.addresses[2],'percent':'50'},
        ],self.network,self.resolve,validate_cashaddr)
        self.assertEqual(plan[0]['address'],self.addresses[0])
        self.assertEqual(plan[0]['units'],500000)
        self.assertEqual(plan[1]['address'],self.addresses[2])

    def test_pinned_address_survives_future_wallet_rotation(self):
        old=validate_destinations([{'type':'wallet','wallet_id':'first','percent':'100'}],self.network,self.resolve,validate_cashaddr)
        self.map['first']=self.addresses[2]
        saved=validate_destinations([{'type':'wallet','wallet_id':'first','address':old[0]['address'],'percent':'100'}],
                                    self.network,self.resolve,validate_cashaddr,old)
        self.assertEqual(saved[0]['address'],self.addresses[0])
        self.assertEqual(validate_saved_destinations(saved,self.network,lambda wid:wid in self.map,validate_cashaddr)[0]['address'],self.addresses[0])

    def test_network_duplicate_sum_and_missing_wallet_rejected(self):
        cases=[
            [{'type':'address','address':self.addresses[0],'percent':'90'}],
            [{'type':'address','address':self.addresses[0],'percent':'50'},
             {'type':'address','address':self.addresses[0],'percent':'50'}],
            [{'type':'wallet','wallet_id':'unknown','percent':'100'}],
        ]
        for items in cases:
            with self.subTest(items=items), self.assertRaises((ValueError,KeyError)):
                validate_destinations(items,self.network,self.resolve,validate_cashaddr)
        with self.assertRaises(ValueError):
            validate_destinations([{'type':'address','address':self.addresses[0],'percent':'100'}],
                                   'mainnet',self.resolve,validate_cashaddr)

    def test_mining_settings_solo_multiple_and_pool_control(self):
        settings=MiningSettings(network=self.network,reward_address=self.addresses[0],
            reward_splits=((self.addresses[0],500000),(self.addresses[1],500000)),cpu_percent=0,gpu_percent=25)
        settings.validate()
        with self.assertRaises(ValueError):
            MiningSettings(network=self.network,reward_address=self.addresses[0],
                reward_splits=((self.addresses[0],500000),(self.addresses[1],400000)),cpu_percent=0,gpu_percent=25).validate()

    def test_ui_contract_collapsible_compact_and_middle_elision(self):
        html=(ROOT/'ui/index.html').read_text(encoding='utf-8')
        self.assertIn('id="miningRewardDetails"',html)
        self.assertNotIn('id="miningRewardDetails" open', html)
        self.assertIn('id="rewardRows"',html)
        self.assertIn('id="addRewardDestination"',html)
        self.assertIn('shortenRewardWallet',html)
        self.assertIn('ctx.measureText',html)
        self.assertIn('address.slice(0,n)',html)
        self.assertIn("address.slice(-suffixLength)",html)
        self.assertIn('data-reward-wallet',html)

if __name__=='__main__':unittest.main()
