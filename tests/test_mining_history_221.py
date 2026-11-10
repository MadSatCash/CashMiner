"""Historial v2.2.1, basado en situaciones reales de la prueba FABLOUS."""
import tempfile
import unittest
from pathlib import Path
from cashminer.mining.history import MiningHistory
from cashminer.network.peer_store import PeerStore

A='00000000b57fd5696471beb85ef77f3a2afd8902ed7f16b9c345a858be2a906f'
B='0000000024468127169af9384231dfce700f40400b28789fcfdace5a271bbaeb'
C='000000001207928dcba67ab9cc40dfaec2c04605933259b78f4abe336589a13b'
B_COMP='0000000022b8767dd036d7c8fabd2fc90fa77314bd49337eeb8203dda737f7bb'
D='000000009ef24049b03410dc0da8f1af2d7161b751acee5f5ae7bff742b81d83'
D_COMP='00000000aec484d14b3120b9376be9bcc28a3fb57d0229eb3ae16b70167b5182'
PRE='00000000059f6fcc3f419548350072281e26e18a793bb9d4d09892064d8f4be7'

def found(height,hash_,parent):
    return f'[2026-11-06 18:43:42] [tempnet:found-observation] height={height} hash={hash_} prev_hash={parent} coinbase_value_sats=250000000 reward_address=bchtest:test stored_path=folder/block.json'

def observation(height,hash_,parent,work,peer='15.204.253.47:48335'):
    return (f'[2026-11-06 18:44:06] [tempnet:p2p-observation] peer={peer} candidate_height={height} '
            f'candidate_hash={hash_} candidate_prev_hash={parent} candidate_chainwork={work} '
            f'cache_height={height} cache_hash={hash_} cache_chainwork={work} rounds=1')

def header(height,hash_,parent,peer='15.204.253.47:48335'):
    return (f'[2026-11-06 18:44:01] [tempnet:peer-observation] block_hash={hash_} height={height} '
            f'peer={peer} header[0] hash={hash_} prev_hash={parent} nBits=1d00ffff')

class MiningHistory221Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'networks'/'tempnet_fablous_2026.sqlite'
        self.h=MiningHistory(self.db)
        self.h.start('bchtest:destination');self.h.started()

    def test_block_does_not_count_when_only_broadcast(self):
        self.h.process_line(found(359364,A,PRE))
        self.h.process_line('[broadcast:OK] peer pidió bloque y fue enviado')
        self.assertEqual(self.h.count(),0)
        self.h.process_line(header(359364,A,PRE))
        self.assertEqual(self.h.count(),1)
        self.h.process_line(header(359364,A,PRE))
        self.assertEqual(self.h.count(),1)

    def test_real_reorg_case_and_stale_before_broadcast(self):
        self.h.process_line(found(359364,A,PRE));self.h.process_line(observation(359364,A,PRE,100))
        self.h.process_line(found(359365,B,A));self.h.process_line(header(359365,B,A))
        self.assertEqual(self.h.count(),2)
        # Igual que en el registro real: h359366 enlaza a un competidor de h359365.
        self.h.process_line(observation(359366,C,B_COMP,110))
        self.assertEqual(self.h.count(),1)
        self.assertEqual(self.h.blocks[B]['status'],'outside')
        self.h.process_line(found(359367,D,C))
        self.h.process_line(f'[2026-11-06 18:48:19] [tempnet:stale] BLOQUE OBSOLETO: padre={C} nuevo_tip={D_COMP} altura=359367; guardado para análisis, no difundido')
        self.assertEqual(self.h.summary()['stale'],1)
        self.assertEqual(self.h.count(),1)

    def test_stronger_chain_can_restore_old_block_later(self):
        self.h.process_line(found(359365,B,A));self.h.process_line(header(359365,B,A))
        self.h.process_line(observation(359366,C,B_COMP,110))
        self.assertEqual(self.h.blocks[B]['status'],'outside')
        self.h.process_line(observation(359365,B,A,120))
        self.assertEqual(self.h.blocks[B]['status'],'observed')
        self.assertEqual(self.h.count(),1)

    def test_equal_work_competitor_does_not_revoke_automatically(self):
        self.h.process_line(found(359365,B,A))
        self.h.process_line(observation(359365,B,A,100))
        self.assertEqual(self.h.count(),1)
        self.h.process_line(observation(359365,B_COMP,A,100,'second-peer'))
        self.assertEqual(self.h.count(),1)

    def test_headers_from_unrelated_chain_are_not_taken_as_our_block(self):
        self.h.process_line(found(359365,B,A))
        junk=f'[2026-11-06 18:56:48] [tempnet:peer-observation] block_hash={B} height=359365 peer=bad header[0] hash={C} prev_hash={D}'
        self.h.process_line(junk)
        for i in range(1,2000):
            self.h.process_line(f'[tempnet:peer-observation] block_hash={B} height=359365 peer=bad header[{i}] hash={C} prev_hash={D}')
        self.assertEqual(self.h.count(),0)
        self.assertEqual(len(self.h.links),0)

    def test_history_reopens_without_deleting_peer_tables(self):
        peers=PeerStore(self.db)
        peers.add_peer('127.0.0.1',48333)
        self.h.process_line(found(359364,A,PRE));self.h.process_line(header(359364,A,PRE))
        self.h.set_log('cashminer.py_26-11-06_18h43m11s.log')
        self.h.finish('Minería detenida por usuario')
        restored=MiningHistory(self.db)
        self.assertEqual(restored.count(),1)
        sessions=restored.recent()
        self.assertEqual(sessions[0]['log_name'],'cashminer.py_26-11-06_18h43m11s.log')
        self.assertEqual(len(sessions[0]['blocks']),1)
        self.assertTrue(peers.peers())
        restored.start('bchtest:otra')
        self.assertEqual(restored.count(),0)
        self.assertEqual(len(restored.recent()),2)

if __name__=='__main__':unittest.main()
