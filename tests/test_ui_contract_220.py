"""Contrato mínimo de la interfaz compacta. No necesita navegador ni Internet."""
import re
import unittest
from pathlib import Path

UI=Path(__file__).resolve().parents[1]/'ui/index.html'

class CompactUiContract220(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=UI.read_text(encoding='utf8')

    def test_switch_accessible_con_estado_y_configuracion(self):
        self.assertIn('data-miner-toggle=',self.html)
        self.assertIn('role=\"switch\" aria-checked=',self.html)
        self.assertIn('data-miner-gear=',self.html)
        self.assertIn('class="activity-message"',self.html)
        self.assertIn('m.mining_activity',self.html)
        self.assertNotIn('id="minerStats"',self.html)
        self.assertIn('id="configBlocksValue"',self.html)
        self.assertIn('Soluciones PoW halladas',self.html)

    def test_dialogos_propios_sin_confirm_prompt_ni_alert(self):
        self.assertIn('id="decisionOverlay"',self.html)
        self.assertIn('async()=>{',self.html)
        for fn in ('confirm(', 'prompt(', 'alert('):
            self.assertNotIn(fn,self.html)
        self.assertIn('id="minPeersMining"',self.html)
        self.assertIn('askDecision(',self.html)

    def test_selector_red_y_logs_se_conservan(self):
        for marker in ('id="walletNetworkSelect"','id="minerCards"','id="minerLog"','id="logLimit"',
                       'id="logDetails"','id="logSearchNext"','id="logToEnd"'):
            self.assertIn(marker,self.html)
        self.assertIn('CashMiner v2.11',self.html)
        self.assertIn('.layout{grid-template-columns:minmax(0,1fr)}',self.html)

if __name__=='__main__':unittest.main()
