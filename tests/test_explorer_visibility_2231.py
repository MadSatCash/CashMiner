"""v2.2.3.1: visibilidad del explorador sin sockets reales ni GPU."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.network.p2p import Probe
from cashminer.network.peer_store import PeerStore


class ExplorerProgress2231(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db = root / 'networks' / 'tempnet_fablous_2026.sqlite'
        self.patches = [
            patch.object(app_server, 'PREF_FILE', root / 'settings.json'),
            patch.object(app_server, 'network_db_path', lambda net: root / 'networks' / (net + '.sqlite')),
        ]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.service=app_server.CashMinerService()
        self.addCleanup(self.service.stop_all)
        # Exploración de red elegida explícitamente
        self.service.prefs['miner_settings']['tempnet_fablous_2026'].update(explorer_interval=120,peer_concurrency=2,peers_per_round=5)
        self.store=PeerStore(self.db)

    def test_progress_counts_actual_probes_not_total_time(self):
        self.store.add_peer('8.8.8.8',48335)
        self.store.add_peer('1.1.1.1',48335)
        def fake_probe(net,ip,port,**kw):
            if ip=='8.8.8.8':
                return Probe(ip,port,connected=True,handshake=True,addr_received=True,
                             candidates=[('8.8.8.8',48335),('9.9.9.9',48335)])
            return Probe(ip,port,connected=False,handshake=False,error='test refusal',candidates=[])
        with patch.object(app_server,'discover_dns',return_value=[]), patch.object(app_server,'probe_peer',side_effect=fake_probe):
            self.service.start_exploring('tempnet_fablous_2026')
            limit=time.time()+5
            while time.time()<limit:
                p=self.service.explorer_snapshot('tempnet_fablous_2026')
                if p['phase']=='Esperando':break
                time.sleep(.025)
            self.assertEqual(p['phase'],'Esperando')
            self.assertEqual(p['total'],5)  # 2 conocidos + 3 bootstrap (puede haber solapamiento)
            self.assertEqual(p['processed'],p['total'])
            self.assertEqual(p['handshake_ok'],1)
            self.assertEqual(p['failed'],p['total']-1)
            self.assertEqual(p['addresses_received'],2)
            self.assertEqual(p['new_peers'],1)
            self.assertEqual(self.store.get('9.9.9.9',48335)['ip'],'9.9.9.9')
            self.assertTrue(p['next_round_at'])
            state=self.service.state('tempnet_fablous_2026')
            self.assertEqual(state['explorer_progress']['new_peers'],1)
            self.service.stop_exploring('tempnet_fablous_2026')
            self.assertFalse(self.service.explorer_manual['tempnet_fablous_2026'])
            self.assertEqual(self.service.explorer_snapshot('tempnet_fablous_2026')['phase'],'Detenido')

    def test_single_probe_collects_failure_without_claiming_chain(self):
        self.store.add_peer('8.8.8.8',48335)
        p=self.service.explorer_progress_by_network['tempnet_fablous_2026']
        self.service.explorer_progress=p  # simular el worker activo de esta red
        p.update(total=1,phase='Explorando')
        self.service._round_known={('8.8.8.8',48335)}
        fake=Probe('8.8.8.8',48335,connected=True,handshake=False,error='bad handshake',candidates=[])
        with patch.object(app_server,'probe_peer',return_value=fake):
            self.service._probe_one(app_server.get_network('tempnet_fablous_2026'),self.store,'8.8.8.8',48335)
        p=self.service.explorer_snapshot('tempnet_fablous_2026')
        self.assertEqual((p['processed'],p['tcp_ok'],p['handshake_ok'],p['failed']),(1,1,0,1))
        self.assertEqual(p['new_peers'],0)

    def test_connectivity_and_chain_are_not_the_same(self):
        self.store.add_peer('8.8.8.8',48335)
        self.store.record('8.8.8.8',48335,'connect_attempt')
        self.store.record('8.8.8.8',48335,'tcp_ok')
        self.store.record('8.8.8.8',48335,'handshake_ok')
        self.store.record('8.8.8.8',48335,'chain_incompatible')
        p=next(x for x in self.service.peers('tempnet_fablous_2026') if x['endpoint']=='8.8.8.8:48335')
        self.assertEqual(p['connectivity'],'Sano')
        self.assertEqual(p['chain_status'],'Incompatible observada')
        self.assertTrue(p['score']>0)

if __name__=='__main__': unittest.main()
