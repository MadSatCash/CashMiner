"""Regresiones HTTP: la red del engranaje no es un selector global del backend."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app
from cashminer.network.peer_store import PeerStore


class ExplicitContext214a8(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for p in (patch.dict(os.environ,{'CASHMINER2_DATA_DIR':str(self.root),
                                       'CASHMINER_DATA_DIR':str(self.root)}),
                  patch.object(app,'PREF_FILE',self.root/'settings.json'),
                  patch.object(app,'network_db_path',lambda n:self.root/'networks'/(n+'.sqlite'))):
            p.start();self.addCleanup(p.stop)
        self.service=app.CashMinerService()
        self.local=app.LocalServer(self.service)
        self.worker=threading.Thread(target=self.local.serve_forever,daemon=True)
        self.worker.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.local.shutdown();self.worker.join(timeout=4);self.local.server_close()
        self.service.stop_all()

    def query(self,path,body=None):
        headers={'X-CashMiner-Session':self.local.secret}
        data=None
        if body is not None:
            headers['Content-Type']='application/json'
            data=json.dumps(body).encode('utf8')
        req=urllib.request.Request(f'http://127.0.0.1:{self.local.server_port}'+path,
                                    data=data,headers=headers,method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req,timeout=5) as resp:
                return resp.status,json.loads(resp.read())
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())

    def test_reading_other_network_has_zero_side_effects(self):
        self.service.prefs['network']='testnet3'  # preferencia histórica pre-refactor
        self.service.prefs['miner_settings']['testnet4']['cpu_percent']=23
        before=json.dumps(self.service.prefs,sort_keys=True)
        status,test4=self.query('/api/state?miner_network=testnet4')
        self.assertEqual(status,200)
        self.assertEqual(test4['miner_network'],'testnet4')
        self.assertEqual(test4['settings']['cpu_percent'],23)
        status,mainnet=self.query('/api/state?miner_network=mainnet')
        self.assertEqual(status,200)
        self.assertEqual(mainnet['miner_network'],'mainnet')
        self.assertEqual(mainnet['settings']['cpu_percent'],0)
        status,default=self.query('/api/state')
        self.assertEqual(status,200)
        self.assertEqual(default['miner_network'],'mainnet')
        self.assertEqual(before,json.dumps(self.service.prefs,sort_keys=True))
        self.assertIsNone(self.service.explorer_network)
        self.assertFalse(self.service.explore_stop.is_set())
        self.assertEqual(self.query('/api/network',{'network':'chipnet'})[0],404)

    def test_settings_are_network_isolated_and_implicit_writes_rejected(self):
        status,response=self.query('/api/settings',{'network':'chipnet','peer_timeout':7})
        self.assertEqual(status,200)
        self.assertEqual(self.service.prefs['miner_settings']['chipnet']['peer_timeout'],7)
        self.assertEqual(self.service.prefs['miner_settings']['mainnet']['peer_timeout'],4)
        status,error=self.query('/api/settings',{'peer_timeout':11})
        self.assertEqual(status,400)
        self.assertIn('red explícita',error['error'])
        status,response=self.query('/api/settings',{'ui_language':'en'})
        self.assertEqual(status,200)
        self.assertEqual(self.service.prefs['ui_language'],'en')

    def test_peers_are_read_for_the_requested_network(self):
        PeerStore(self.root/'networks'/'chipnet.sqlite').add_peer('8.8.8.8',48333)
        code,chip=self.query('/api/peers?network=chipnet')
        self.assertEqual(code,200)
        self.assertEqual([peer['endpoint'] for peer in chip],['8.8.8.8:48333'])
        code,main=self.query('/api/peers?network=mainnet')
        self.assertEqual(code,200)
        self.assertEqual(main,[])
        self.assertEqual(self.query('/api/peers')[0],400)
        self.assertEqual(self.query('/api/miner/history')[0],400)
        self.assertEqual(self.query('/api/logs/sessions')[0],400)

    def test_other_network_control_does_not_stop_active_explorer(self):
        # Simulate a worker mid-probe, no sockets nor mining.
        self.service.explorer_network='testnet3'
        self.service.explorer_state='Explorando'
        self.service.explore_thread=threading.Thread(target=lambda:self.service.close_event.wait(1),daemon=True)
        self.service.explore_thread.start()
        status,state=self.query('/api/state?miner_network=chipnet')
        self.assertEqual(status,200)
        self.assertEqual(state['explorer_state'],'Detenido')
        self.assertEqual(self.service.explorer_state,'Explorando')
        self.assertFalse(self.service.explore_stop.is_set())
        status,error=self.query('/api/peers/stop',{'network':'chipnet'})
        self.assertEqual(status,200)
        self.assertTrue(error['ok'])
        self.assertEqual(self.service.explorer_state,'Explorando')
        self.assertFalse(self.service.explore_stop.is_set())
        # Cierre por el cleanup, no reuso de global.


if __name__=='__main__': unittest.main()
