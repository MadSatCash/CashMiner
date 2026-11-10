"""v2.2.3.2: reasoned explorer lifecycle and non-invasive UI contract."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server as app_server
from cashminer.network.p2p import Probe
from cashminer.network.peer_store import PeerStore

class ExplorerPolish2232(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for patcher in (patch.object(app_server,'PREF_FILE',root/'settings.json'),
                        patch.object(app_server,'network_db_path',lambda n:root/'networks'/(n+'.sqlite'))):
            patcher.start();self.addCleanup(patcher.stop)
        self.service=app_server.CashMinerService()
        self.addCleanup(self.service.stop_all)
        # Exploración de red elegida explícitamente
        self.service.prefs['miner_settings']['tempnet_fablous_2026'].update(explorer_interval=60,peer_concurrency=2,peers_per_round=2,peer_timeout=1)
        PeerStore(root/'networks'/'tempnet_fablous_2026.sqlite').add_peer('8.8.8.8',48333)

    def test_explicit_user_stop_records_only_when_thread_finishes(self):
        def fake_probe(net,ip,port,**kw):
            return Probe(ip,port,connected=True,handshake=True,candidates=[])
        with patch.object(app_server,'discover_dns',return_value=[]),patch.object(app_server,'probe_peer',side_effect=fake_probe):
            self.service.start_exploring('tempnet_fablous_2026')
            deadline=time.time()+5
            while time.time()<deadline and self.service.explorer_snapshot('tempnet_fablous_2026')['phase']!='Esperando':time.sleep(.02)
            self.assertEqual(self.service.explorer_snapshot('tempnet_fablous_2026')['phase'],'Esperando')
            self.service.stop_exploring('tempnet_fablous_2026')
            self.assertFalse(self.service.explorer_manual['tempnet_fablous_2026'])
            self.assertTrue(self.service.explore_thread.is_alive())
        lines=[msg for _,msg in self.service.get_logs('peers',0)['lines']]
        starts=[x for x in lines if 'Exploración continua iniciada por el usuario' in x]
        stops=[x for x in lines if 'Exploración continua detenida por el usuario' in x]
        self.assertEqual(len(starts),1)
        self.assertEqual(len(stops),1)
        self.assertLess(lines.index(starts[0]),lines.index(stops[0]))
        self.service.stop_exploring('tempnet_fablous_2026')
        self.assertEqual(sum('Exploración continua detenida por el usuario' in m for _,m in self.service.get_logs('peers',0)['lines']),1)

    def test_failed_discovery_is_not_recorded_as_user_stop(self):
        with patch.object(app_server,'discover_dns',side_effect=RuntimeError('intentional test failure')):
            self.service.start_exploring('tempnet_fablous_2026')
            deadline=time.time()+3
            while time.time()<deadline and not any('Exploración finalizada por error' in l for _,l in self.service.get_logs('peers',0)['lines']):time.sleep(.02)
            self.assertTrue(self.service.explore_thread.is_alive())
        lines=[m for _,m in self.service.get_logs('peers',0)['lines']]
        self.assertTrue(any('Exploración finalizada por error' in l for l in lines))
        self.assertFalse(any('Exploración continua detenida por el usuario' in l for l in lines))

    def test_ui_sections_chevrons_status_and_log_copy_present(self):
        ui=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text(encoding='utf8')
        self.assertIn('id="knownPeersDetails"',ui)
        self.assertIn('id="explorerHeaderState"',ui)
        self.assertIn('id="knownPeersCount"',ui)
        self.assertIn('id="copyExplorerLog"',ui)
        self.assertIn("details[open] > summary::after{transform:rotate(225deg)}",ui)
        self.assertNotIn("summary:after{content:'⌄'",ui)
        self.assertIn("if($('peerActivityDetails')?.open)await updatePeerLog()",ui)
        self.assertIn("if($('knownPeersDetails')?.open",ui)

if __name__=='__main__':unittest.main()
