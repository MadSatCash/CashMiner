"""Testnet3/4: registrar evidencia de cabeceras, sin contar broadcast como aceptación."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cashminer.mining.history import MiningHistory

H='00000000a560c17b24688f7d0a59f2a1cfebb619e126c09b8a08b8906ea9526f'
PRE='000000000d1b947a8316aab5340d092e04b7053a3e84b086aa23bd3ca4ffae31'
OTHER='000000007da8dbd8514006eff2f8aad80a560e367be661e5c7ba541c564891ec'
T='[2026-11-08 05:58:13] '

def found_lines(height=1735718, block=H, parent=PRE):
    return [
        T+'    coinbase_value: 19531250 sat',
        T+'[!!!] BLOQUE ENCONTRADO',
        T+'      hash: '+block,
        T+'[+] Bloque guardado en: C:\\local\\block.json',
        T+'[*] Broadcasteando bloque por P2P en network=testnet peers=[]',
        T+'[debug:block]',
        T+f'    height: {height}',
        T+'    hash: '+block,
        T+'    prev_hash: '+parent,
        T+'    bits: 1d00ffff',
        T+'    ntime: 1794128289',
    ]

def electrum_lines(height=1735718, tip=H, parent=PRE, accepted=True):
    return [T+'[*] Verificación post-broadcast por Electrum:',
            T+f'    tip_height: {height}', T+'    tip_hash: '+tip,
            T+'    tip_prev_hash: '+parent,
            T+f'    accepted_as_tip: {accepted}',
            T+'    accepted_parent: False']

def p2p_lines(tips=None, children=None, competitors=None):
    tips=[] if tips is None else tips
    children=[] if children is None else children
    competitors=[] if competitors is None else competitors
    return [T+'[*] Verificación post-broadcast por P2P:',
            T+'    checked_peers: 3',
            T+f'    aceptaron (tip+hijos): {len(tips)+len(children)}/3',
            T+f'    accepted_as_tip_by: {tips!r}',
            T+f'    accepted_as_parent_by: {children!r}',
            T+'    still_on_parent_by: []',
            T+f'    competitor_at_height_by: {competitors!r}',
            T+'    seen_neither_by: []',
            T+'    errors: []']

class TestnetMiningHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'network.sqlite'
        self.h=MiningHistory(self.path,'testnet3')
        self.h.start('bchtest:abc')
    def lines(self,lines):
        for line in lines:self.h.process_line(line)

    def test_broadcast_alone_does_not_count(self):
        self.lines(found_lines())
        self.assertEqual(self.h.summary()['found_total'],1)
        self.assertEqual(self.h.summary()['pending'],1)
        self.assertEqual(self.h.count(),0)
        self.lines([T+'[broadcast:OK] 10.0.0.1 -> peer pidió bloque y fue enviado'])
        self.assertEqual(self.h.count(),0)

    def test_electrum_hash_and_height_required(self):
        self.lines(found_lines())
        self.lines(electrum_lines(tip=OTHER))
        self.assertEqual(self.h.count(),0)
        self.lines(electrum_lines(height=1735719,tip=H))
        self.assertEqual(self.h.count(),0)
        self.lines(electrum_lines())
        self.assertEqual(self.h.count(),1)
        self.assertEqual(self.h.summary()['pending'],0)
        self.lines(electrum_lines())
        self.assertEqual(self.h.count(),1)
        self.assertEqual(MiningHistory(self.path,'testnet3').count(),1)
        self.assertEqual(self.h.blocks[H]['stored_path'],r'C:\local\block.json')

    def test_electrum_descendant_proves_previous_block(self):
        self.lines(found_lines())
        data=[T+'[*] Verificación post-broadcast por Electrum:',
              T+'    tip_height: 1735719',
              T+'    tip_hash: '+OTHER,
              T+'    tip_prev_hash: '+H,
              T+'    accepted_as_tip: False',T+'    accepted_parent: True']
        self.lines(data)
        self.assertEqual(self.h.count(),1)

    def test_p2p_can_prove_inclusion_without_electrum(self):
        self.lines(found_lines())
        self.lines(p2p_lines(children=['10.0.0.1:18333']))
        self.assertEqual(self.h.count(),1)
        self.assertEqual(self.h.blocks[H]['evidence'],'p2p_header_tip_or_descendant')

    def test_no_peer_evidence_keeps_pending(self):
        self.lines(found_lines())
        self.lines(p2p_lines())
        self.assertEqual(self.h.summary()['pending'],1)
        self.assertEqual(self.h.count(),0)

    def test_multiple_competing_peers_can_mark_outside(self):
        self.lines(found_lines())
        self.lines(p2p_lines(competitors=['peerA','peerB']))
        self.assertEqual(self.h.summary()['outside'],1)
        self.assertEqual(self.h.count(),0)

    def test_new_session_ignores_previous_log(self):
        self.lines(found_lines());self.lines(electrum_lines())
        self.h.start('bchtest:next')
        self.assertEqual(self.h.count(),0)
        self.assertEqual(self.h.summary()['found_total'],0)

    def test_testnet4_uses_the_same_protocol_format(self):
        h=MiningHistory(Path(self.temp.name)/'testnet4.sqlite','testnet4')
        h.start('bchtest:new')
        for line in found_lines()+electrum_lines():h.process_line(line)
        self.assertEqual(h.count(),1)

if __name__=='__main__':unittest.main()
