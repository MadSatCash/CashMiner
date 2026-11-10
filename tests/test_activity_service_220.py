import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server as app_server

class MiningService220(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
        self.p=patch.object(app_server,'PREF_FILE',Path(self.tmp.name)/'settings.json');self.p.start();self.addCleanup(self.p.stop)
        self.s=app_server.CashMinerService()

    def test_hashrate_activa_estado_real_sin_engano_por_cero(self):
        with patch.object(self.s.sessions['mainnet'].mining,'running',return_value=True):
            self.s.miner_line_for('mainnet','[2026-11-06] [tempnet] Minando altura=359292 nBits=1d00ffff')
            self.s.miner_line_for('mainnet','[2026-11-06] [*] engine=CUDA0 h=359292 rate_total=164,380,000 H/s')
            self.assertEqual(self.s.sessions['mainnet'].miner_state,'Minando')
            self.assertEqual(self.s.state()['mining_activity']['phase'],'hashing')
            self.s.miner_line_for('mainnet','[2026-11-06] [*] engine=CUDA0 h=359292 rate_total=0 H/s')
            self.assertEqual(self.s.sessions['mainnet'].miner_state,'Minando')
            self.assertEqual('Minando · 164,38 MH/s',self.s.state()['mining_activity']['message'])

    def test_error_de_proceso_no_se_muestra_como_mineria_activa(self):
        self.s.sessions['mainnet'].miner_state='Terminado';self.s.sessions['mainnet'].last_error='Falló al iniciar'
        self.assertEqual(self.s.state()['mining_activity']['phase'],'error')

if __name__=='__main__':unittest.main()
