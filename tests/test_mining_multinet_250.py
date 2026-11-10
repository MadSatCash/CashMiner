"""Offline regressions for v2.5: no real mining, no RPC/Stratum peers, no secrets."""
from __future__ import annotations
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.mining import bridge as miner_bridge
from cashminer.wallet.legacy_hd import address_from_secret
from cashminer.mining.bridge import MiningSettings, MINING_MODES, MinerController

ROOT=Path(__file__).resolve().parents[1]

class Multinet250(unittest.TestCase):
    def test_modes_per_network_and_compatibility(self):
        self.assertEqual(set(MINING_MODES),{'mainnet','testnet3','testnet4','chipnet','regtest','tempnet_fablous_2026'})
        testaddr=address_from_secret(1,'testnet4')
        with self.assertRaises(ValueError):
            MiningSettings('testnet4',testaddr,mode='not-a-mode').validate()
        MiningSettings('mainnet',address_from_secret(1,'mainnet'),mode='p2p-tip').validate()
        with self.assertRaises(ValueError):
            MiningSettings('mainnet',address_from_secret(1,'mainnet'),mode='p2p-tip',tip_source='unsupported').validate()
        MiningSettings('testnet4',testaddr,gpu_percent=0,mode='p2p-tip').validate()
        MiningSettings('mainnet',address_from_secret(1,'mainnet'),gpu_percent=0,
                       mode='rpc',rpc_url='http://127.0.0.1:8332').validate()
        MiningSettings('mainnet','',gpu_percent=0,mode='pool',pool_url='stratum+ssl://pool.example:3333',
                       pool_user='public.worker').validate()

    def test_rpc_and_pool_validation(self):
        m=address_from_secret(1,'mainnet')
        for url in ('http://external.example/rpc','file:///etc/passwd','https://bob:secret@example.org:443/rpc',
                    'https://example.org/rpc#fragment'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                MiningSettings('mainnet',m,gpu_percent=0,mode='rpc',rpc_url=url).validate()
        for url in ('stratum+tcp://pool.example','https://pool.example:80','stratum+ssl://x:3333/api',
                    'stratum+ssl://user:pw@pool.example:3333'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                MiningSettings('mainnet','',gpu_percent=0,mode='pool',pool_url=url,
                               pool_user='account.worker').validate()

    def test_ephemeral_rpc_password_never_enters_settings_or_state(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td}), \
                 patch.object(app_server,'PREF_FILE',Path(td)/'settings.json'):
                svc=app_server.CashMinerService()
                try:
                    # Mainnet defaults to P2P in new installs: RPC readiness is
                    # separately tested after selecting the RPC mode.
                    svc.prefs['mining_modes']['mainnet']='rpc'
                    self.assertFalse(svc.state()['mining_connection_ready'])
                    result=svc.configure_mining_connection({'network':'mainnet','mode':'rpc',
                        'rpc_url':'http://127.0.0.1:8332','rpc_user':'sample','rpc_password':'SAMPLE-NEVER-STORE'})
                    self.assertTrue(result['configured'])
                    self.assertTrue(svc.state()['mining_connection_ready'])
                    self.assertNotIn('SAMPLE-NEVER-STORE',str(svc.state()))
                    self.assertNotIn('SAMPLE-NEVER-STORE',(Path(td)/'settings.json').read_text())
                    self.assertNotIn('rpc_url',(Path(td)/'settings.json').read_text())
                    self.assertEqual(svc.prefs['mining_modes']['mainnet'],'rpc')
                    with self.assertRaises(ValueError):
                        svc.configure_mining_connection({'network':'mainnet','mode':'p2p-tip','tip_source':'unsupported'})
                finally:
                    svc.stop_all()

    def test_real_local_http_connection_endpoint_and_access_control(self):
        import json
        import urllib.error
        import urllib.request
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td}), \
                 patch.object(app_server,'PREF_FILE',Path(td)/'settings.json'):
                svc=app_server.CashMinerService()
                server=app_server.LocalServer(svc)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    body=json.dumps({'network':'mainnet','mode':'pool',
                        'pool_url':'stratum+ssl://pool.example:3333','pool_user':'test.worker',
                        'pool_password':'TEMP-TEST-SECRET'}).encode()
                    endpoint='http://127.0.0.1:'+str(server.server_port)+'/api/miner/connection'
                    req=urllib.request.Request(endpoint,data=body,method='POST',headers={'Content-Type':'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(req,timeout=4)
                    self.assertEqual(denied.exception.code,403)
                    req.add_header('X-CashMiner-Session',server.secret)
                    with urllib.request.urlopen(req,timeout=4) as r:
                        response=json.load(r)
                    self.assertEqual(response['mode'],'pool')
                    self.assertTrue(svc.state()['mining_connection_ready'])
                    self.assertNotIn('TEMP-TEST-SECRET',json.dumps(svc.state()))
                    self.assertNotIn('TEMP-TEST-SECRET',(Path(td)/'settings.json').read_text())
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
                    server.server_close()
                    svc.stop_all()

    def test_new_wallet_destination_without_secret_vault_access(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td}), \
                 patch.object(app_server,'PREF_FILE',Path(td)/'settings.json'):
                svc=app_server.CashMinerService()
                try:
                    store=svc.wallet_sync.store('testnet4')
                    # Public test vector. No real-user recovery words.
                    # Simulate Windows DPAPI only for this offline test.
                    with patch('cashminer.wallet.store.protect_seed',side_effect=lambda x,w:b'mock:'+x):
                        created=store.create('Sample',mnemonic='abandon '*11+'about',
                                             new_type='bip39',derivation_path="m/44'/145'/0'")
                    # Cada consulta especifica la red de destino
                    choices=svc.miner_wallet_choices('testnet4')
                    sample=[x for x in choices if x['id']==created['id']][0]
                    self.assertEqual(sample['source'],'v23')
                    self.assertEqual(svc._mining_wallet_address(created['id'],'testnet4'),(sample['address'],''))
                    svc.select_mining_wallet(created['id'],'testnet4')
                    self.assertEqual(svc.state('testnet4')['mining_wallet'],created['id'])
                finally:
                    svc.stop_all()

    def test_selected_sqlite_peers_in_original_testnet_route(self):
        # Only header selection, NEVER network access.
        sys.path.insert(0,str(ROOT/'mining_engine'))
        import miner as engine
        with patch.object(engine,'NETWORK','testnet4'), \
             patch.object(engine,'BROADCAST_PEERS',['127.0.0.1:28333']), \
             patch.dict(os.environ,{'CASHMINER2_SQLITE_PEERS':'1'}):
            self.assertEqual(engine.load_testnet_p2p_tip_peers_from_db(5),['127.0.0.1:28333'])

    def test_process_argv_never_contains_secrets(self):
        class FakeProc:
            def __init__(self):
                self.stdout=io.StringIO('')
            def poll(self): return 0
            def wait(self): return 0
        cases=[
            MiningSettings('mainnet',address_from_secret(1,'mainnet'),gpu_percent=0,mode='rpc',
                rpc_url='http://127.0.0.1:8332',rpc_user='operator',rpc_password='TEST-RPC-SECRET'),
            MiningSettings('mainnet','',gpu_percent=0,mode='pool',
                pool_url='stratum+ssl://pool.example:3333',pool_user='worker.test',pool_password='TEST-POOL-SECRET'),
            MiningSettings('testnet4',address_from_secret(1,'testnet4'),gpu_percent=0,
                mode='p2p-tip',peers=('127.0.0.1:28333',)),
            MiningSettings('tempnet_fablous_2026',address_from_secret(1,'tempnet_fablous_2026'),
                gpu_percent=0,mode='p2p-tip',peers=('127.0.0.1:48333',)),
        ]
        for item in cases:
            with self.subTest(mode=item.mode,network=item.network),tempfile.TemporaryDirectory() as td:
                recorded=[]
                def fake_popen(args,**kwargs):
                    recorded.append((args,kwargs['env']))
                    return FakeProc()
                with patch.dict(os.environ,{'CASHMINER2_DATA_DIR':td}), \
                     patch.object(miner_bridge.subprocess,'Popen',side_effect=fake_popen):
                    ctl=MinerController(lambda line:None,lambda *args:None)
                    ctl.start(item)
                    ctl.wait_for_log_close()
                self.assertEqual(len(recorded),1)
                args,env=recorded[0]
                self.assertEqual(args[args.index('--miner-mode')+1],item.mode)
                self.assertEqual(args[args.index('--network')+1],miner_bridge.NETWORK_CLI[item.network])
                for secret in ('TEST-RPC-SECRET','TEST-POOL-SECRET'):
                    self.assertNotIn(secret,' '.join(args))
                if item.mode=='rpc':
                    self.assertEqual(env['CASHMINER2_RPC_PASSWORD'],'TEST-RPC-SECRET')
                    self.assertEqual(env['CASHMINER2_RPC_URL'],'http://127.0.0.1:8332')
                if item.mode=='pool':
                    self.assertEqual(env['BCH_POOL_PASSWORD'],'TEST-POOL-SECRET')
                if item.network=='testnet4':
                    self.assertEqual(env['CASHMINER2_SQLITE_PEERS'],'1')
                if item.network=='tempnet_fablous_2026':
                    self.assertNotIn('CASHMINER2_SQLITE_PEERS',env)
                self.assertNotIn('BCH_PEER_DB_DSN',env)

if __name__=='__main__':unittest.main()
