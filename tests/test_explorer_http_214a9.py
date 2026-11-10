"""HTTP/UI contract for independently controlled explorer modes (no real sockets)."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from cashminer.app import server as app

class ExplorerControlsHTTP214a9(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for p in (patch.dict(os.environ,{'CASHMINER2_DATA_DIR':str(root),'CASHMINER_DATA_DIR':str(root)}),
                  patch.object(app,'PREF_FILE',root/'settings.json'),
                  patch.object(app,'network_db_path',lambda n:root/'networks'/(n+'.sqlite'))):
            p.start();self.addCleanup(p.stop)
        self.svc=app.CashMinerService()
        self.http=app.LocalServer(self.svc)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.http.shutdown();self.thread.join(timeout=4)
        self.http.server_close();self.svc.stop_all()

    def post(self,path,payload):
        req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}'+path,
            data=json.dumps(payload).encode(),
            headers={'X-CashMiner-Session':self.http.secret,'Content-Type':'application/json'},
            method='POST')
        try:
            with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as err:return err.code,json.loads(err.read())

    def test_controls_are_independent_and_validation_is_strict(self):
        self.assertEqual(self.post('/api/peers/mode',{'mode':'automatic','network':'mainnet','enabled':False})[0],200)
        self.assertFalse(self.svc.prefs['explorer_auto_by_network']['mainnet'])
        self.assertTrue(self.svc.prefs['explorer_auto_by_network']['testnet3'])
        self.assertEqual(self.post('/api/peers/global',{'mode':'automatic','enabled':False})[0],200)
        self.assertTrue(self.svc.prefs['explorer_auto_by_network']['testnet3'])
        self.assertTrue(self.svc.prefs['explorer_continuous_master'])
        self.assertEqual(self.post('/api/peers/global',{'mode':'continuous','enabled':False})[0],200)
        self.assertEqual(self.post('/api/peers/mode',{'mode':'automatic','network':'mainnet','enabled':'false'})[0],400)
        self.assertEqual(self.post('/api/peers/mode',{'mode':'automatic','network':'missing','enabled':True})[0],400)
        self.assertEqual(self.post('/api/peers/mode',{'mode':'automatic','enabled':True})[0],200)  # global semantics
        result=self.svc.state('chipnet')
        self.assertEqual(len(result['explorer_all']),len(app.NETWORKS))
        self.assertFalse(result['explorer_all']['regtest']['auto_enabled'])
        self.assertEqual(result['explorer_all']['chipnet']['network'],'chipnet')

    def test_frontend_contains_all_controls_in_bottom_summary(self):
        html=(Path(__file__).resolve().parents[1]/'ui/index.html').read_text()
        for name in ('explorerAutoToggle','explorerToggle','explorerAutoMaster',
                     'explorerContinuousMaster','explorerGlobalDetails','explorerGlobalRows'):
            self.assertIn('id="'+name+'"',html)
        self.assertLess(html.index('id="explorerAutoToggle"'),html.index('id="peerActivityDetails"'))
        self.assertLess(html.index('id="peerActivityDetails"'),html.index('id="explorerGlobalDetails"'))
        self.assertIn("await api('/api/peers/global'",html)
        self.assertIn("await api('/api/peers/mode'",html)

if __name__=='__main__':unittest.main()
