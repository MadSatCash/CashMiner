"""Pruebas de la proyección de eventos del motor a la GUI."""
import unittest
from cashminer.mining.activity import MiningActivity

class MiningActivityTests(unittest.TestCase):
    def test_inicio_sync_y_hashrate_sin_perder_el_estado(self):
        m=MiningActivity();m.reset(10)
        self.assertEqual(m.snapshot(True,'Iniciando',now=11)['message'],'Iniciando minería')
        m.observe('[tempnet:p2p] peer height=42',12)
        self.assertEqual(m.snapshot(True,'Iniciando',now=13)['phase'],'syncing')
        m.observe('[tempnet] Minando altura=43',14)
        self.assertEqual(m.snapshot(True,'Iniciando',now=15)['phase'],'preparing')
        m.observe('[*] engine=CUDA0 rate_total=135,000,000 H/s',16)
        self.assertEqual(m.snapshot(True,'Minando',now=17)['message'],'Minando · 135,00 MH/s')
        m.observe('[*] engine=CUDA0 rate_total=0 H/s',18)
        self.assertEqual(m.snapshot(True,'Minando',now=19)['message'],'Minando · 135,00 MH/s')
        self.assertEqual(m.snapshot(False,'Detenido',now=20)['message'],'Minería detenida')

    def test_no_declara_bloque_aceptado_por_la_red(self):
        m=MiningActivity();m.reset(1)
        m.observe('[*] engine=CUDA0 rate_total=140,000,000 H/s',2)
        m.observe('[!!!] BLOQUE ENCONTRADO',3)
        self.assertIn('Solución PoW',m.snapshot(True,'Minando',now=4)['event_message'])
        m.observe('[*] Broadcasteando bloque por P2P',5)
        self.assertIn('Anunciando',m.snapshot(True,'Minando',now=6)['event_message'])
        m.observe('[broadcast:OK] peer pidió el bloque y fue enviado',7)
        self.assertIn('Anunciando',m.snapshot(True,'Minando',now=8)['event_message'])
        m.observe('[tempnet:peer-observation:start] height=100',9)
        self.assertIn('Consultando',m.snapshot(True,'Minando',now=10)['event_message'])
        m.observe('[tempnet:peer-observation:end] responses=3 errors=1',11)
        self.assertEqual(m.snapshot(True,'Minando',now=12)['phase'],'hashing')
        m.observe('[tempnet:post-broadcast] en_cadena_observada=True',13)
        self.assertIn('cadena de cabeceras',m.snapshot(True,'Minando',now=14)['event_message'])
        self.assertNotIn('aceptado',m.snapshot(True,'Minando',now=14)['message'].lower())
        self.assertEqual(m.snapshot(True,'Minando',now=24)['phase'],'hashing')

    def test_obsoleto_no_difundido_y_error_terminacion(self):
        m=MiningActivity();m.reset(1)
        m.observe('[tempnet:stale] BLOQUE OBSOLETO: no difundido',2)
        self.assertIn('no difundida',m.snapshot(True,'Minando',now=3)['event_message'])
        self.assertEqual(m.snapshot(False,'Terminado','Exit 1',now=4)['phase'],'error')

    def test_reset_no_mezcla_eventos_de_sesiones(self):
        m=MiningActivity();m.reset(1)
        m.observe('[!!!] BLOQUE ENCONTRADO',2)
        m.reset(3)
        self.assertEqual(m.snapshot(True,'Iniciando',now=4)['phase'],'starting')

if __name__=='__main__':unittest.main()
