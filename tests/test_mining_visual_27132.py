"""Estados estables y aviso independiente en la tarjeta de minería."""
import unittest
from pathlib import Path
from cashminer.mining.activity import MiningActivity

class MiningVisual27132(unittest.TestCase):
    def test_first_fast_block_still_shows_mining(self):
        m=MiningActivity();m.reset(0)
        m.observe('[*] Tip obtenido desde Electrum',1)
        self.assertEqual(m.snapshot(True,'Iniciando',now=1)['message'],'Preparando trabajo de minería')
        m.observe('[*] Delegando al motor real de minado...',2)
        m.observe('[!!!] BLOQUE ENCONTRADO',3)
        m.observe('[*] Broadcasteando bloque por P2P',3.1)
        snap=m.snapshot(True,'Iniciando',now=4)
        self.assertEqual(snap['phase'],'hashing')
        self.assertTrue(snap['message'].startswith('Minando'))
        self.assertIn('Anunciando',snap['event_message'])
        self.assertEqual(m.snapshot(True,'Minando',now=20)['event_message'],'')

    def test_hashrate_continues_when_peer_event_occurs(self):
        m=MiningActivity();m.reset(0)
        m.observe('[*] engine=CUDA0 rate_total=125,000,000 H/s',1)
        m.observe('[*] engine=CUDA0 rate_total=0 H/s',2)
        m.observe('[tempnet:peer-observation:start] block_hash=a',3)
        self.assertEqual(m.snapshot(True,'Minando',now=4)['message'],'Minando · 125,00 MH/s')
        self.assertIn('Consultando',m.snapshot(True,'Minando',now=4)['event_message'])

    def test_error_is_immediate_and_not_hidden(self):
        m=MiningActivity();m.reset(0)
        m.observe('[*] engine=CUDA0 rate_total=125,000,000 H/s',1)
        m.observe('[!] Error en modo p2p-tip: failed',2)
        self.assertEqual(m.snapshot(True,'Minando',now=2.1)['phase'],'error')
        self.assertEqual(m.snapshot(False,'Detenido',now=3)['event_message'],'')

    def test_ui_secondary_event_and_duplicate_guard(self):
        html=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text(encoding='utf-8')
        self.assertIn('m.mining_activity?.event_message',html)
        self.assertIn('pendingMinerToggles.has(net)',html)
        self.assertIn("e.message.includes('Minería ya activa')",html)
        self.assertIn('Bloques propios observados en cadena',html)

if __name__=='__main__':unittest.main()
