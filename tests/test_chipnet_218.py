"""Faster Blocks: real headers, independent BCHN vectors, branch state and wallet."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock

from cashminer.network import chipnet_consensus as c
from cashminer.wallet.store import WalletStore
from cashminer.wallet.send import WalletSender
from cashminer.wallet.crypto import script_hash
from cashminer.wallet.legacy_hd import address_from_secret
from cashminer.wallet import electrum

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner
from native_headers import NativeHeaderClient

RAW=(ROOT/'tests/fixtures/chipnet_218_headers.bin').read_bytes()
META=json.loads((ROOT/'tests/fixtures/chipnet_218_headers.json').read_text())
def header(height):
    start=(height-META['first_height'])*80
    return RAW[start:start+80]

class ChipnetConsensus218(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=NativeHeaderClient('chipnet',[],lambda *args:None)
        for i in range(11,len(RAW)//80):cls.client._append(cls.client.chain,RAW[i*80:(i+1)*80])
        cls.client.work=cls.client.chain[-1]['chainwork']

    def context(self,height):
        blockhash=hashlib.sha256(hashlib.sha256(header(height)).digest()).digest()[::-1].hex()
        return self.client.context_at(height,blockhash)

    def test_full_real_history_crosses_activation_with_valid_pow_bits_mtp_and_linkage(self):
        self.assertEqual(hashlib.sha256(RAW).hexdigest(),META['sha256'])
        self.assertEqual(self.client.tip['tip_height'],META['last_height'])
        self.assertEqual(self.client.tip['consensus_context'].activation_height,332450)
        self.assertEqual(self.context(332449).next_interval,600)
        self.assertEqual(self.context(332450).next_interval,60)
        self.assertEqual(c.block_subsidy_sats(332450,self.context(332449)),2500000000)
        self.assertEqual(c.block_subsidy_sats(332451,self.context(332450)),250000000)
        self.assertEqual(c.conservative_block_size(self.context(332449)),2000000)
        self.assertEqual(c.conservative_block_size(self.context(332450)),200000)

    def test_exact_cpp_bchn_asert_vectors(self):
        vectors=json.loads((ROOT/'tests/fixtures/chipnet_218_asert.json').read_text())
        self.assertEqual(vectors['cases_compared'],9967)
        for row in vectors['vectors']:
            with self.subTest(height=row['height'],time=row['time']):
                ctx=c.ChipnetContext(row['height'],'11'*32,row['time'],row['time']-100,row['activation_height'])
                self.assertEqual(c.expected_bits(ctx.parent_height,ctx.parent_time,row['candidate_time'],ctx),int(row['bits'],16))

    def test_minimum_difficulty_boundary_is_strict_and_interval_aware(self):
        for height,delay in [(332449,1200),(335090,120)]:
            ctx=self.context(height)
            before=c.expected_bits(height,ctx.parent_time,ctx.parent_time+delay,ctx)
            self.assertNotEqual(before,c.POW_LIMIT_BITS)
            self.assertEqual(c.expected_bits(height,ctx.parent_time,ctx.parent_time+delay+1,ctx),c.POW_LIMIT_BITS)
            with patch.object(miner,'NETWORK','chipnet'),patch.object(miner,'log'):
                bits=f'{before:08x}';target=miner.bits_to_target(bits)
                rolled=miner.roll_bits_for_ntime(bits,target,miner.target_to_le_bytes(target),height+1,
                    ctx.parent_time,ctx.parent_time+delay+1,context=ctx)
                self.assertEqual(rolled[0],'1d00ffff')

    def test_context_is_branch_local_and_reorg_can_remove_activation(self):
        def history(time,activation):
            rows=[{'height':400000+i,'time':time+i,'hash':f'{i:064x}'} for i in range(11)]
            rows[-1]['activation_height']=activation
            return rows
        old=history(c.ACTIVATION_MTP-100,None)
        fast=history(c.ACTIVATION_MTP+100,None)
        a=c.context_for_parent(old[-1],old);b=c.context_for_parent(fast[-1],fast)
        self.assertEqual(a.next_interval,600);self.assertEqual(b.next_interval,60)
        self.assertIsNone(a.activation_height);self.assertEqual(b.activation_height,400010)
        self.assertIsNone(c.context_for_parent(old[-1],old).activation_height)
        with self.assertRaises(ValueError):c.expected_bits(a.parent_height+1,a.parent_time,a.parent_time+1,a)
        with patch.object(miner,'NETWORK','chipnet'),self.assertRaises(ValueError):
            miner.compute_next_bits_for_network(a.parent_height,a.parent_time,a.parent_time+1)

    def test_halving_alignment_includes_all_ten_blocks_in_the_new_chunk(self):
        boundary=c.PINNED_ACTIVATION_HEIGHT+(420000-c.PINNED_ACTIVATION_HEIGHT)*10
        for height in range(boundary-10,boundary+2):
            ctx=c.ChipnetContext(height-1,'11'*32,1800000000,1800000000,c.PINNED_ACTIVATION_HEIGHT)
            self.assertEqual(c.block_subsidy_sats(height,ctx),250000000 if height<boundary-9 else 125000000)

    def test_verified_context_drives_engine_subsidy_and_coinbase_raw_height(self):
        ctx=self.context(335090)
        with patch.object(miner,'NETWORK','chipnet'):
            self.assertEqual(miner.get_block_subsidy_sats(335091,context=ctx),250000000)
            # Even a 30 BCH reward (including fees) cannot have Mina's forbidden v1 shape.
            tx=miner.build_coinbase_tx(335091,0,3000000000,b'\x51')
            self.assertEqual(int.from_bytes(tx[:4],'little'),2)
            script=miner.build_coinbase_script_sig(335091,0)
            self.assertTrue(script.startswith(miner.encode_push(miner.encode_script_num(335091))))
            stats=miner.estimate_block_stats_from_bits('1d00ffff',1000000)
            self.assertEqual(stats['target_interval_seconds'],60)
            self.assertLess(stats['p_target_interval'],stats['p_10min'])

    def test_native_job_passes_the_same_context_to_the_backend(self):
        solo=miner.BCHSoloMiner.__new__(miner.BCHSoloMiner)
        tip=self.client.tip;tip['peers_ok']=['127.0.0.1:48333','127.0.0.2:48333']
        solo.native_client=MagicMock();solo.native_client.sync.return_value=tip
        import threading
        solo._tempnet_watch_lock=threading.Lock();solo.invalidator=MagicMock()
        solo.c_scanner=None
        with patch.object(miner,'NETWORK','chipnet'),patch.object(miner,'log'),\
             patch.object(solo,'_ensure_native_tipwatch'),patch.object(solo,'_p2p_has_gpu',return_value=False),\
             patch.object(solo,'mine_template_multiprocess',side_effect=lambda **kw:kw):
            values=solo.mine_native_p2p_tip()
        self.assertEqual(values['coinbase_value'],250000000)
        self.assertEqual(values['height'],META['last_height']+1)
        self.assertEqual(solo._consensus_context,tip['consensus_context'])

    def test_electrum_history_is_checked_before_it_can_be_used_for_mining(self):
        def request(method,params):
            if method=='blockchain.block.header':return header(params[0]).hex()
            start,count=params
            offset=(start-META['first_height'])*80
            return {'count':count,'hex':RAW[offset:offset+count*80].hex()}
        client=NativeHeaderClient('chipnet',[],lambda *args:None)
        ctx=client.verify_electrum_chain(request,333223,c.POST_UPGRADE_CHECKPOINTS[-1][1])
        self.assertEqual(ctx.activation_height,332450)
        self.assertEqual(ctx.next_interval,60)
        def corrupted(method,params):
            reply=request(method,params)
            if isinstance(reply,dict):reply['hex']='00'+reply['hex'][2:]
            return reply
        broken=NativeHeaderClient('chipnet',[],lambda *args:None)
        with self.assertRaises(ValueError):broken.verify_electrum_chain(corrupted,333223,c.POST_UPGRADE_CHECKPOINTS[-1][1])
        self.assertFalse(broken.chain)

    def test_assisted_job_rebaselines_to_verified_parent_and_caps_mempool(self):
        base=self.context(335090);chosen=self.context(335091)
        tls={'tip_hash_le':bytes.fromhex(base.parent_hash)[::-1],'tip_hash_hex':base.parent_hash,
            'tip_height':base.parent_height,'tip_time':base.parent_time,'tip_bits_hex':header(335090)[72:76][::-1].hex(),
            'tip_header80':header(335090),'anchor_height':335080,'anchor_hash_hex':'11'*32}
        peer={**tls,'compatible_peers':['127.0.0.1:48333','127.0.0.2:48333'],
            'incompatible_peers':[],'errors':[],'used_direct_electrum_tip':True}
        solo=miner.BCHSoloMiner.__new__(miner.BCHSoloMiner)
        solo.tip_watcher=None;solo.invalidator=MagicMock();solo.invalidator.invalidate_event.is_set.return_value=False
        solo.cuda_scanner=None;solo.opencl_scanner=None;solo.c_scanner=None
        solo.reward_splits=[]
        watcher=MagicMock();watcher.stats.return_value={'conectado_desde_s':0,'headers':0,'invalidaciones':0}
        def checked(tls_tip,p2p_tip):
            p2p_tip['tip_bits_hex']=header(335091)[72:76][::-1].hex()
            return chosen
        with patch.object(miner,'NETWORK','chipnet'),patch.object(miner,'log'),\
             patch.object(miner,'fetch_testnet_tip_from_electrum',return_value=tls),\
             patch.object(miner,'fetch_testnet3_tip_from_peers_using_electrum_tip',return_value=peer),\
             patch.object(solo,'_chipnet_assisted_context',side_effect=checked),\
             patch.object(miner,'ElectrumTipWatcher',return_value=watcher),\
             patch.object(miner,'select_mempool_txs_for_block',return_value=([],[],0)) as mempool,\
             patch.object(solo,'mine_template_multiprocess',side_effect=lambda **kw:kw):
            values=solo.mine_testnet3_p2p_tip()
        self.assertEqual(values['prev_hash'],chosen.parent_hash)
        self.assertEqual(values['height'],chosen.parent_height+1)
        self.assertEqual(watcher.rebaseline.call_args.kwargs['parent_hash_be_hex'],chosen.parent_hash)
        self.assertEqual(mempool.call_args.kwargs['max_block_bytes'],200000)

    def test_cache_reconstructs_branch_state_and_old_rules_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'headers.bin'
            cached=NativeHeaderClient('chipnet',[],lambda *a:None,cache_path=p)
            cached.chain=list(self.client.chain);cached.save_cache()
            restored=NativeHeaderClient('chipnet',[],lambda *a:None,cache_path=p)
            self.assertEqual(restored.tip['consensus_context'],self.client.tip['consensus_context'])
            p.write_bytes(p.read_bytes().replace(b'CashMinerHeaders2-mina:',b'CashMinerHeaders1:',1))
            self.assertFalse(NativeHeaderClient('chipnet',[],lambda *a:None,cache_path=p).chain)

class ChipnetWallet218(unittest.TestCase):
    def test_maturity_exact_boundaries_and_a_coinbase_spanning_activation(self):
        h=332451
        self.assertFalse(c.coinbase_mature('chipnet',h,h+998))
        self.assertTrue(c.coinbase_mature('chipnet',h,h+999))
        creation=332400
        self.assertFalse(c.coinbase_mature('chipnet',creation,332948))
        self.assertTrue(c.coinbase_mature('chipnet',creation,332949))
        for net in ('mainnet','testnet3','testnet4','regtest','tempnet_fablous_2026'):
            self.assertFalse(c.coinbase_mature(net,10,108));self.assertTrue(c.coinbase_mature(net,10,109))

    def test_balance_aggregate_address_and_send_share_the_maturity_rule(self):
        with tempfile.TemporaryDirectory() as td:
            store=WalletStore('chipnet',Path(td));wallet=store.create('Mina',legacy_hex='01'.zfill(64),expected_address=address_from_secret(1,'chipnet'))
            wid=wallet['id'];address=store.get(wid)['first_address'];creation=332451
            rows=[{'branch':0,'idx':0,'address':address,'scripthash':script_hash(address,'chipnet'),'used':1}]
            utxo={'txid':'12'*32,'vout':0,'value':1000000,'height':creation,'address':address,'coinbase':True,'tokens':False}
            for confirmations in (100,999,1000):
                store.apply_snapshot(wid,rows,[utxo],[],creation+confirmations-1,'ab'*32,'mock.test:50002')
                with store.db() as db:db.execute('UPDATE addresses SET status_known=1 WHERE wallet_id=?',(wid,))
                wallets=store.list();mature=confirmations==1000
                self.assertEqual(wallets[0]['available_sats'],1000000 if mature else 0)
                self.assertEqual(wallets[0]['immature_sats'],0 if mature else 1000000)
                self.assertEqual(store.total_unique(wallets)['available_sats'],1000000 if mature else 0)
                page=store.address_page(wid)['addresses'][0]
                self.assertEqual(page['available_sats'],1000000 if mature else 0)
                sender=WalletSender()
                if mature:
                    prepared=sender.prepare(store,wid,address_from_secret(2,'chipnet'),'0.001')
                    self.assertEqual(prepared['amount_sats'],100000)
                else:
                    with self.assertRaisesRegex(ValueError,'UTXOs gastables'):
                        sender.prepare(store,wid,address_from_secret(2,'chipnet'),'0.001')

    def test_server_choice_groups_by_hash_before_height_and_refuses_ties(self):
        raw=header(333223).hex();fork=raw[:-8]+'12345678'
        peers={('a',1):(333230,raw),('b',2):(333240,raw),('rogue',3):(900000,fork)}
        def factory(network,host,port,**kwargs):
            client=MagicMock();client.__enter__.return_value=client
            client.tip_height_hash.return_value=(peers[(host,port)][0],'aa'*32)
            client.rpc.return_value=peers[(host,port)][1]
            return client
        with patch.object(electrum,'ElectrumClient',side_effect=factory):
            ordered,info=electrum.select_chipnet_servers(list(peers))
            self.assertEqual(ordered,[('b',2),('a',1)])
            self.assertEqual(info['validated_servers'],2)
            with self.assertRaisesRegex(electrum.ElectrumError,'divergentes'):
                electrum.select_chipnet_servers([('a',1),('rogue',3)])

if __name__=='__main__':unittest.main()
