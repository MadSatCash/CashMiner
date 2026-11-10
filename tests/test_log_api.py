"""Pruebas HTTP locales. No inicia el minero ni consulta peers."""
import json
import os
import tempfile
import threading
from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cashminer.app.server import CashMinerService, LocalServer
from cashminer.app import server as app_server
from cashminer.platform import log_archive


class LogAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'CASHMINER2_DATA_DIR':self.tmp.name})
        self.env.start();self.addCleanup(self.env.stop)
        self.settings_patch=patch.object(app_server,'PREF_FILE',Path(self.tmp.name)/'settings.json')
        self.settings_patch.start();self.addCleanup(self.settings_patch.stop)
        folder = log_archive.logs_dir();folder.mkdir(parents=True,exist_ok=True)
        self.name='cashminer.py_26-11-06_03h31m16s.log'
        (folder/self.name).write_text('Inicio\nERROR X\nFin\n',encoding='utf8')
        self.service = CashMinerService()
        self.server=LocalServer(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close()

    def call(self, url, payload=None, authenticated=True):
        import urllib.parse
        headers={}
        if authenticated:headers['X-CashMiner-Session']=self.server.secret
        if payload is not None:
            headers['Content-Type']='application/json'
            payload=json.dumps(payload).encode('utf-8')
        req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+url,
                                   data=payload, headers=headers, method='POST' if payload is not None else 'GET')
        with urllib.request.urlopen(req,timeout=4) as resp:
            data=resp.read()
        return json.loads(data)

    def test_search_delete_retention_and_saved_view(self):
        import urllib.parse
        q=urllib.parse.urlencode({'name':self.name,'q':'error'})
        r=self.call('/api/logs/search?'+q)
        self.assertEqual(r['line'],'ERROR X')
        view={'name':self.name,'font':14,'scroll':56,'start':0,'end':18,'expanded':True,'panel_scroll':30}
        self.assertEqual(self.call('/api/logs/view',view),{'ok':True})
        self.assertEqual(self.call('/api/state')['settings']['log_view'],view)
        self.assertEqual(self.call('/api/logs/sessions?network=mainnet')['usage']['count'],1)
        self.assertEqual(self.call('/api/logs/prune',{})['deleted'],[])
        self.assertEqual(self.call('/api/logs/delete',{'name':self.name})['deleted'],self.name)
        self.assertEqual(self.call('/api/logs/sessions?network=mainnet')['sessions'],[])

    def test_rejects_foreign_file_and_wrong_auth(self):
        import urllib.parse
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call('/api/logs/delete',{'name':'../../wallets/private.json'})
        self.assertEqual(e.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call('/api/logs/sessions?network=mainnet',authenticated=False)
        self.assertEqual(e.exception.code,403)
        with patch.object(self.service.sessions['mainnet'].mining,'running',return_value=True):
            self.service.sessions['mainnet'].active_log_name=self.name
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.call('/api/logs/delete',{'name':self.name})
            self.assertEqual(e.exception.code,400)

if __name__=='__main__':unittest.main()
