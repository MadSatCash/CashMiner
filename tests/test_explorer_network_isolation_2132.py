"""v2.16: cambiar la red de consulta jamás detiene el explorador."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.network.p2p import Probe
from cashminer.network.peer_store import PeerStore


class ExplorerNetworkIsolation2132(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for p in (patch.dict(os.environ,{'CASHMINER_DATA_DIR':str(self.root)}),
                  patch.object(app_server,'PREF_FILE',self.root/'settings.json'),
                  patch.object(app_server,'network_db_path',lambda n:self.root/'networks'/(n+'.sqlite'))):
            p.start(); self.addCleanup(p.stop)
        self.svc=app_server.CashMinerService()
        self.addCleanup(self.svc.stop_all)

    def test_completed_progress_remains_per_network_and_never_creates_peers(self):
        main=self.svc.explorer_progress_by_network['mainnet']
        test3=self.svc.explorer_progress_by_network['testnet3']
        main.update(round=2,phase='Detenido',total=24,processed=24,handshake_ok=22,new_peers=15227)
        test3.update(round=1,phase='Detenido',total=19,processed=19,handshake_ok=18,new_peers=655)
        self.assertEqual(self.svc.state('mainnet')['explorer_progress']['handshake_ok'],22)
        self.assertEqual(self.svc.state('testnet3')['explorer_progress']['handshake_ok'],18)
        self.assertEqual(self.svc.state('chipnet')['explorer_progress']['new_peers'],0)
        self.assertEqual(self.svc.explorer_snapshot('testnet3')['processed'],19)
        self.assertEqual(self.svc.state('testnet3')['peer_counts']['peers'],0)
        self.assertEqual(self.svc.state('mainnet')['peer_counts']['peers'],0)
        # Leer estados de otras redes no altera ninguna selección persistente.
        self.assertEqual(self.svc.prefs['network'],'mainnet')
        self.assertNotIn('testnet3', str(self.svc.prefs['network']))

    def test_view_other_network_while_probe_runs_does_not_stop_or_reassign(self):
        self.svc.prefs['miner_settings']['testnet3'].update(peers_per_round=1,
            peer_concurrency=1,peer_timeout=1,explorer_interval=600)
        PeerStore(self.root/'networks'/'testnet3.sqlite').add_peer('8.8.8.8',18333)
        entered,release=threading.Event(),threading.Event()

        def probe(net,ip,port,**kwargs):
            entered.set()
            if not release.wait(5):raise RuntimeError('Probe release timeout')
            return Probe(ip,port,connected=True,handshake=True,addr_received=False,candidates=[])

        with patch.object(app_server,'discover_dns',return_value=[]), \
             patch.object(app_server,'probe_peer',side_effect=probe):
            self.svc.start_exploring('testnet3')
            self.assertTrue(entered.wait(4))
            state=self.svc.state('testnet4')
            self.assertEqual(state['explorer_network'],'testnet4')
            self.assertEqual(state['explorer_state'],'Detenido')
            self.assertEqual(state['explorer_progress']['processed'],0)
            self.assertFalse(self.svc.explore_stop.is_set())
            # Una solicitud para otra red queda en cola, no toca el probe en curso.
            self.svc.start_exploring('testnet4')
            self.assertTrue(self.svc.explorer_manual['testnet4'])
            self.svc.stop_exploring('testnet4')
            self.assertFalse(self.svc.explorer_manual['testnet4'])
            self.assertFalse(self.svc.explore_stop.is_set())
            release.set()
            limit=time.time()+5
            while time.time()<limit and self.svc.explorer_snapshot('testnet3')['phase']!='Esperando':
                time.sleep(.02)
            self.assertEqual(self.svc.explorer_snapshot('testnet3')['processed'],1)
            self.assertEqual(self.svc.explorer_snapshot('testnet3')['handshake_ok'],1)
            self.assertEqual(self.svc.state('testnet4')['explorer_progress']['processed'],0)
            self.svc.stop_exploring('testnet3')
            self.assertFalse(self.svc.explorer_manual['testnet3'])
            self.assertTrue(self.svc.explore_thread.is_alive())  # único coordinador, en espera
        self.assertEqual(self.svc.state('testnet3')['explorer_state'],'Detenido')
        self.assertEqual(self.svc.explorer_snapshot('testnet3')['processed'],1)


if __name__=='__main__':unittest.main()
