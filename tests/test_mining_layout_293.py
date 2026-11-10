"""Regression tests for the focused v2.9.3 mining settings improvements."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server
from cashminer.mining.bridge import MiningSettings
from cashminer.wallet.legacy_hd import address_from_secret

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text(encoding='utf-8')

class MiningModalLayout293(unittest.TestCase):
    def test_order_and_collapsible_sections(self):
        block=HTML.split('function openMineConfig(){',1)[1].split('`,true);',1)[0]
        parts=['Destino de recompensas','Actividad e historial de minería',
               'Red y modalidad de minería','Hardware</summary>',
               'Conexiones para minar','Servidores Electrum de minería',
               'Diagnóstico del minero · Logs originales','Peer Explorer ·',
               'Datos P2P · almacenamiento compartido']
        positions=[block.index(x) for x in parts]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('<details class="settings-section" id="miningModeDetails"><summary>',block)
        self.assertIn('<details class="settings-section" id="minPeersDetails"><summary>',block)
        self.assertNotIn('<details class="settings-section" id="minPeersDetails" open',block)
        self.assertNotIn('<details class="settings-section" id="miningModeDetails" open',block)
    def test_number_field_and_confirmation_kept(self):
        block=HTML.split('function openMineConfig(){',1)[1].split('`,true);',1)[0]
        self.assertIn('type="number" id="minPeersMining" min="1" max="80" step="1"',block)
        self.assertNotIn('<select class="select" id="minPeersMining">',block)
        for key in ['id="saveMiningConnection"','id="saveMinPeersBtn"',
                    'id="minerLogSession"','id="logCopyAll"','id="logDownload"',
                    'id="refreshMineHistory"','id="logDetails"']:
            self.assertIn(key,block)
        self.assertIn('Number.isSafeInteger(n)',HTML)
        self.assertIn("min_peers_mining:Number($('minPeersMining').value)",HTML)

class MinimumPeers293(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(server,'PREF_FILE',Path(self.tmp.name)/'settings.json')
        p.start();self.addCleanup(p.stop)
        e=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.tmp.name})
        e.start();self.addCleanup(e.stop)
        self.s=server.CashMinerService();self.addCleanup(self.s.stop_all)
    def test_all_allowed_values_persist_per_network(self):
        for n in (1,2,3,5,80):
            with self.subTest(n=n):
                self.s.set_prefs({'network':'testnet3','min_peers_mining':n})
                self.assertEqual(server._prefs_read()['miner_settings']['testnet3']['min_peers_mining'],n)
        self.assertEqual(server._prefs_read()['miner_settings']['chipnet']['min_peers_mining'],2)
    def test_bad_values_rejected(self):
        for n in (0,81,-1,2.5,False,'2.5','abc',None):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    self.s.set_prefs({'network':'chipnet','min_peers_mining':n})
    def test_mining_settings_validates_minimum(self):
        address=address_from_secret(5,'testnet3')
        for n in (1,2,5,80):
            with self.subTest(n=n):
                MiningSettings(network='testnet3',reward_address=address,min_peers_mining=n).validate()
        for n in (0,81,False):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    MiningSettings(network='testnet3',reward_address=address,min_peers_mining=n).validate()
    def test_engine_receives_threshold_as_environment(self):
        bridge=(ROOT/'src/cashminer/mining/bridge.py').read_text()
        engine=(ROOT/'mining_engine/miner.py').read_text()
        self.assertIn("CASHMINER2_MIN_PEERS=str(settings.min_peers_mining)",bridge)
        self.assertIn("CASHMINER2_MIN_PEERS','1'",engine)
        self.assertIn("CASHMINER2_MIN_PEERS','2'",engine)
        self.assertIn('compatible < required',engine)
        self.assertIn('independent_peers < required',engine)

if __name__=='__main__':unittest.main()
