"""Startup source selection, persistence and engine isolation (no public mining)."""
import io
import json
import os
import sys
import tempfile
import threading
import subprocess
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

from cashminer.app import server
from cashminer.mining import bridge, peer_sources
from cashminer.network.networks import NETWORKS
from cashminer.network.peer_store import PeerStore
from cashminer.wallet.legacy_hd import address_from_secret

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mining_engine'))
import miner as engine


class PeerSourceSelection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=PeerStore(Path(self.tmp.name)/'peers.sqlite')
        self.store.add_peer('1.1.1.1',8333)
        self.store.record('1.1.1.1',8333,'handshake_ok')

    def test_sqlite_exclusive_never_resolves_dns_or_injects_bootstrap(self):
        with patch.object(peer_sources,'discover_dns') as dns:
            decision=peer_sources.initial_mining_peers(NETWORKS['mainnet'],'sqlite',self.store)
        self.assertEqual(decision['peers'],('1.1.1.1:8333',));dns.assert_not_called()

    def test_empty_sqlite_fails_even_when_bootstrap_exists(self):
        empty=Mock();empty.peers.return_value=[]
        with patch.object(peer_sources,'discover_dns') as dns,self.assertRaisesRegex(ValueError,'No hay candidatos'):
            peer_sources.initial_mining_peers(NETWORKS['tempnet_fablous_2026'],'sqlite',empty)
        dns.assert_not_called()

    def test_dns_exclusive_does_not_read_sqlite(self):
        store=Mock()
        with patch.object(peer_sources,'discover_dns',return_value=[('2.2.2.2',8333,'seed')]) as dns:
            result=peer_sources.initial_mining_peers(NETWORKS['mainnet'],'dns',store)
        self.assertEqual(result['peers'],('2.2.2.2:8333',));store.peers.assert_not_called()
        dns.assert_called_once()

    def test_combined_consults_both_and_deduplicates_ipv4_and_ipv6(self):
        self.store.add_peer('2001:4860:4860::8888',8333)
        self.store.record('2001:4860:4860::8888',8333,'handshake_ok')
        with patch.object(peer_sources,'discover_dns',return_value=[
                ('1.1.1.1',8333,'seed'),('2001:4860:4860::8888',8333,'seed'),('2.2.2.2',8333,'seed')]) as dns:
            result=peer_sources.initial_mining_peers(NETWORKS['mainnet'],'combined',self.store)
        self.assertEqual(set(result['peers']),{'1.1.1.1:8333','[2001:4860:4860::8888]:8333','2.2.2.2:8333'})
        self.assertEqual(len(result['peers']),3);dns.assert_called_once()

    def test_dns_empty_does_not_use_sqlite(self):
        with patch.object(peer_sources,'discover_dns',return_value=[]),self.assertRaises(ValueError):
            peer_sources.initial_mining_peers(NETWORKS['mainnet'],'dns',self.store)

    def test_tempnet_has_no_dns_seeds_and_reports_it(self):
        with patch.object(peer_sources,'discover_dns',return_value=[]),self.assertRaisesRegex(ValueError,'no tiene DNS seeds'):
            peer_sources.initial_mining_peers(NETWORKS['tempnet_fablous_2026'],'dns',self.store)

    def test_combined_empty_dns_keeps_known_sqlite_candidates(self):
        with patch.object(peer_sources,'discover_dns',return_value=[]):
            result=peer_sources.initial_mining_peers(NETWORKS['mainnet'],'combined',self.store)
        self.assertEqual(result['peers'],('1.1.1.1:8333',))

    def test_legacy_preserves_bootstrap_and_does_not_resolve_in_parent(self):
        empty=Mock();empty.peers.return_value=[]
        with patch.object(peer_sources,'discover_dns') as dns:
            result=peer_sources.initial_mining_peers(NETWORKS['tempnet_fablous_2026'],'legacy',empty)
        self.assertEqual(result['peers'],NETWORKS['tempnet_fablous_2026'].bootstrap);dns.assert_not_called()

    def test_shared_cap_and_existing_sqlite_order_are_preserved(self):
        rows=[]
        for i in range(1,90):
            rows.append({'ip':f'8.8.8.{i}','port':8333,'handshake_ok_count':1})
        store=Mock();store.peers.return_value=rows
        expected=peer_sources.choose_mining_peers(rows,[],limit=80)['peers']
        with patch.object(peer_sources,'discover_dns',return_value=[('9.9.9.9',8333,'seed')]) as dns:
            result=peer_sources.initial_mining_peers(NETWORKS['mainnet'],'combined',store)
        self.assertEqual(len(result['peers']),80);self.assertEqual(result['peers'],expected)
        dns.assert_called_once()


class SourcePreferences(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for p in [patch.dict(os.environ,{'CASHMINER_DATA_DIR':str(self.root)}),
                  patch.object(server,'PREF_FILE',self.root/'settings.json')]:
            p.start();self.addCleanup(p.stop)
        self.service=server.CashMinerService();self.addCleanup(self.service.stop_all)

    def configure(self,net,source):
        return self.service.configure_mining_connection({'network':net,'mode':'p2p-tip','peer_source':source})

    def test_existing_preferences_default_to_compatibility_without_rewrite(self):
        for n in NETWORKS:self.assertEqual(self.service.prefs['miner_settings'][n]['peer_source'],'legacy')
        self.assertFalse((self.root/'settings.json').exists())

    def test_sources_persist_and_remain_independent_after_reload(self):
        self.configure('mainnet','dns');self.configure('testnet3','sqlite');self.configure('chipnet','combined')
        prefs=server._prefs_read()['miner_settings']
        self.assertEqual([prefs[n]['peer_source'] for n in ['mainnet','testnet3','chipnet']],['dns','sqlite','combined'])
        self.assertEqual(prefs['testnet4']['peer_source'],'legacy')
        self.assertEqual(self.service.state('mainnet')['mining_peer_source'],'dns')

    def test_invalid_source_rejected_without_changing_preferences(self):
        for source in ('other',None,True,{},[]):
            with self.subTest(source=source),self.assertRaises(ValueError):self.configure('mainnet',source)
        self.assertEqual(self.service.prefs['miner_settings']['mainnet']['peer_source'],'legacy')

    def test_running_miner_rejects_changes(self):
        with patch.object(self.service.sessions['mainnet'].mining,'running',return_value=True),self.assertRaises(ValueError):
            self.configure('mainnet','dns')

    def test_regtest_p2p_requires_explicit_selection_and_uses_native(self):
        self.assertEqual(self.service.prefs['mining_modes']['regtest'],'rpc')
        self.configure('regtest','sqlite')
        self.assertEqual(self.service.prefs['miner_settings']['regtest']['tip_source'],'native')

    def test_startup_passes_selection_to_controller_for_each_public_network(self):
        for n in NETWORKS:
            if n=='regtest':continue
            with self.subTest(network=n):
                self.configure(n,'sqlite')
                st=PeerStore(self.root/'networks'/(n+'.sqlite'))
                st.add_peer('1.1.1.1',NETWORKS[n].default_port);st.record('1.1.1.1',NETWORKS[n].default_port,'handshake_ok')
                slot=self.service.sessions[n]
                with patch.object(slot.mining,'start',return_value=[]) as start,patch.object(peer_sources,'discover_dns') as dns:
                    self.service.start_miner({'network':n,'target_mode':'address','address':address_from_secret(1,n)})
                settings=start.call_args.args[0]
                self.assertEqual(settings.peer_source,'sqlite')
                self.assertEqual(settings.peers,(f'1.1.1.1:{NETWORKS[n].default_port}',));dns.assert_not_called()

    def test_empty_sqlite_stops_before_process_launch(self):
        self.configure('mainnet','sqlite')
        with patch.object(self.service.sessions['mainnet'].mining,'start') as start,self.assertRaisesRegex(ValueError,'No hay candidatos'):
            self.service.start_miner({'network':'mainnet','target_mode':'address','address':address_from_secret(1,'mainnet')})
        start.assert_not_called()

    def test_ui_exposes_three_choices_for_p2p_and_sends_preference(self):
        html=(ROOT/'ui/index.html').read_text(encoding='utf8')
        for text in ['miningPeerSourceSelect','Fuente de peers P2P','DNS seeds + SQLite',"peer_source:$('miningPeerSourceSelect').value", "$('miningPeerSourceFields').classList.toggle('hidden',mode!=='p2p-tip')"]:
            self.assertIn(text,html)

    def test_authenticated_http_roundtrip_preserves_per_network_source(self):
        http=server.LocalServer(self.service)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{http.server_port}'
            headers={'X-CashMiner-Session':http.secret,'Content-Type':'application/json'}
            for network,source in [('mainnet','dns'),('testnet3','sqlite'),('chipnet','combined')]:
                request=urllib.request.Request(base+'/api/miner/connection',headers=headers,
                    data=json.dumps({'network':network,'mode':'p2p-tip','peer_source':source}).encode(),method='POST')
                with urllib.request.urlopen(request,timeout=5) as response:
                    self.assertEqual(response.status,200)
                request=urllib.request.Request(base+'/api/state?miner_network='+network,headers=headers)
                with urllib.request.urlopen(request,timeout=5) as response:
                    self.assertEqual(json.load(response)['mining_peer_source'],source)
        finally:
            http.shutdown();thread.join(3);http.server_close()


class EngineSourceIsolation(unittest.TestCase):
    def setUp(self):
        active=patch.object(engine,'NETWORK','mainnet')
        active.start();self.addCleanup(active.stop)

    def snapshot(self,source='sqlite',peers=None):
        return patch.dict(os.environ,{'CASHMINER2_PEER_SOURCE':source,'CASHMINER2_P2P_PEERS':json.dumps(['1.1.1.1:8333'] if peers is None else peers)})

    def test_all_explicit_sources_use_snapshot_without_dns_or_db(self):
        for source in peer_sources.PEER_SOURCES:
            with self.subTest(source=source),self.snapshot(source),patch.object(engine,'collect_peers_from_seeds') as dns,patch.object(engine,'_import_peer_db_driver') as db:
                self.assertEqual(engine.load_testnet_p2p_tip_peers_from_db(80),['1.1.1.1:8333'])
                dns.assert_not_called();db.assert_not_called()

    def test_explicit_empty_or_malformed_snapshot_never_falls_back(self):
        for raw in ('[]','null','{}','invalid','[5]'):
            with self.subTest(raw=raw),patch.dict(os.environ,{'CASHMINER2_PEER_SOURCE':'sqlite','CASHMINER2_P2P_PEERS':raw}),patch.object(engine,'collect_peers_from_seeds') as dns,self.assertRaises(RuntimeError):
                engine.load_testnet_p2p_tip_peers_from_db(80)
            dns.assert_not_called()

    def test_selection_is_static_even_if_broadcast_defaults_change(self):
        with self.snapshot('dns'),patch.object(engine,'BROADCAST_PEERS',['2.2.2.2:8333']):
            self.assertEqual(engine.selected_p2p_peers(),['1.1.1.1:8333'])

    def test_snapshot_deduplication_and_existing_limit(self):
        with self.snapshot(peers=['1.1.1.1:8333','1.1.1.1:8333','2.2.2.2:8333']):
            self.assertEqual(engine.selected_p2p_peers(1),['1.1.1.1:8333'])

    def test_legacy_retains_original_dns_fallback(self):
        with self.snapshot('legacy'),patch.object(engine,'PEER_DB_DSN',''),patch.dict(os.environ,{'CASHMINER2_SQLITE_PEERS':'0'}),patch.object(engine,'collect_peers_from_seeds',return_value=['2.2.2.2:8333']) as dns:
            self.assertEqual(engine.load_testnet_p2p_tip_peers_from_db(80),['2.2.2.2:8333']);dns.assert_called_once()

    def test_explicit_tempnet_does_not_discover_more_candidates(self):
        with self.snapshot():client=engine.tempnet_candidate_client(['1.1.1.1:8333'],lambda _:None)
        with patch.object(client,'sync_peer',return_value={'peer':'1.1.1.1:8333'}),patch.object(type(client),'tip',new_callable=PropertyMock,return_value={}),patch.object(client,'discover_from_peer') as discover:
            client.sync()
        discover.assert_not_called();self.assertFalse(client.allow_discovery)

    def test_legacy_tempnet_keeps_discovery(self):
        with self.snapshot('legacy'):client=engine.tempnet_candidate_client(['1.1.1.1:8333'],lambda _:None)
        with patch.object(client,'sync_peer',return_value={'peer':'1.1.1.1:8333'}),patch.object(type(client),'tip',new_callable=PropertyMock,return_value={}),patch.object(client,'discover_from_peer',return_value=[]) as discover:
            client.sync()
        discover.assert_called_once();self.assertTrue(client.allow_discovery)


class SourceBridge(unittest.TestCase):
    def test_snapshot_is_exported_and_inherited_source_is_cleared_for_rpc(self):
        class Process:
            def __init__(self):self.stdout=io.StringIO('')
            def poll(self):return 0
            def wait(self):return 0
        for mode in ('p2p-tip','rpc','pool'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                params=dict(network='mainnet',reward_address=address_from_secret(1,'mainnet'),mode=mode,peers=('1.1.1.1:8333',),peer_source='combined',gpu_percent=0)
                if mode=='rpc':params['rpc_url']='http://127.0.0.1:8332'
                if mode=='pool':params.update(pool_url='stratum+tcp://127.0.0.1:3333',pool_user='test.worker')
                with patch.dict(os.environ,{'CASHMINER_DATA_DIR':td,'CASHMINER2_PEER_SOURCE':'sqlite','CASHMINER2_P2P_PEERS':'[]'}),patch.object(bridge,'prepare_runtime',return_value=(Path(td),[])),patch.object(bridge.subprocess,'Popen',return_value=Process()) as popen:
                    ctl=bridge.MinerController(lambda _:None,lambda *_:None)
                    ctl.start(bridge.MiningSettings(**params));ctl.wait_for_log_close()
                env=popen.call_args.kwargs['env']
                if mode=='p2p-tip':
                    self.assertEqual(env['CASHMINER2_PEER_SOURCE'],'combined')
                    self.assertEqual(json.loads(env['CASHMINER2_P2P_PEERS']),['1.1.1.1:8333'])
                    self.assertNotIn('CASHMINER2_SQLITE_PEERS',env)
                    script="import json,miner; miner.NETWORK='mainnet'; print(json.dumps(miner.load_testnet_p2p_tip_peers_from_db(80)))"
                    child=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'mining_engine',env=env,
                                         capture_output=True,text=True,timeout=10,check=True)
                    self.assertEqual(json.loads(child.stdout),['1.1.1.1:8333'])
                else:
                    self.assertNotIn('CASHMINER2_PEER_SOURCE',env);self.assertNotIn('CASHMINER2_P2P_PEERS',env)


if __name__=='__main__':unittest.main()
