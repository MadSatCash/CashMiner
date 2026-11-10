"""Regresiones del visor y del puente, completamente offline."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.platform import log_archive


class Diagnostic217Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ev=patch.dict(os.environ,{'CASHMINER2_DATA_DIR':self.tmp.name})
        self.ev.start();self.addCleanup(self.ev.stop)
        self.settings=patch.object(app_server,'PREF_FILE',Path(self.tmp.name)/'settings.json')
        self.settings.start();self.addCleanup(self.settings.stop)
        log_archive.logs_dir().mkdir(parents=True,exist_ok=True)

    def test_new_install_50_mib_and_existing_setting_preserved(self):
        self.assertEqual(app_server._prefs_read()['log_max_mib'],50)
        app_server.PREF_FILE.write_text('{"log_max_mib":100, "network":"mainnet"}',encoding='utf8')
        self.assertEqual(app_server._prefs_read()['log_max_mib'],100)
        app_server.PREF_FILE.write_text('{"log_max_mib":73, "network":"mainnet"}',encoding='utf8')
        self.assertEqual(app_server._prefs_read()['log_max_mib'],73)

    def test_bridge_startup_log_is_distinct_complete_and_searchable(self):
        name=log_archive.write_startup_failure(
            ['Traceback (most recent call last):','ModuleNotFoundError: No module named tempnet_block_observer'],
            'Proceso minero finalizado inesperadamente (código 1).')
        self.assertRegex(name,r'^cashminer_startup_\d{2}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s_[0-9a-f]{6}\.log$')
        content=log_archive.log_path(name).read_text('utf8')
        self.assertIn('motor no creó su log nativo',content)
        self.assertIn('ModuleNotFoundError',content)
        self.assertIn('código 1',content)
        self.assertEqual(log_archive.search(name,'ModuleNotFoundError')['found'],True)
        self.assertEqual(log_archive.chunk(name)['text'],content)
        self.assertEqual(log_archive.sessions()[0]['name'],name)

    def test_newer_native_log_sorting_and_fifo(self):
        name=log_archive.write_startup_failure(['Missing DLL'],'No se pudo iniciar')
        new='cashminer.py_29-11-06_12h00m00s.log'
        old='cashminer.py_26-11-05_12h00m00s.log'
        for n in [new,old]:(log_archive.logs_dir()/n).write_text('x\n',encoding='utf8')
        ordered=[v['name'] for v in log_archive.sessions()]
        self.assertEqual(ordered[0],new)
        self.assertEqual(ordered[-1],old)
        self.assertIn(name,ordered)
        self.assertFalse(log_archive.prune(50)['over_limit'])

    def test_unexpected_exit_without_native_file_persists_real_output(self):
        svc=app_server.CashMinerService()
        svc.miner_line_for('mainnet','ModuleNotFoundError: No module named tempnet_block_observer')
        svc.miner_exit_for('mainnet',1,None,False)
        self.assertEqual(svc.sessions['mainnet'].miner_state,'Terminado')
        self.assertEqual(svc.sessions['mainnet'].last_error,'Proceso minero finalizado inesperadamente (código 1).')
        self.assertTrue(svc.sessions['mainnet'].active_log_name.startswith('cashminer_startup_'))
        text=log_archive.log_path(svc.sessions['mainnet'].active_log_name).read_text('utf8')
        self.assertIn('ModuleNotFoundError',text)
        self.assertNotIn('Minería detenida por el usuario.',text)
        self.assertEqual(log_archive.usage()['count'],1)

    def test_on_start_exception_no_native_file_and_no_fake_manual_stop(self):
        from cashminer.wallet.legacy_hd import address_from_secret
        svc=app_server.CashMinerService()
        # Testnet address and session are explicit
        address=address_from_secret(1,'tempnet_fablous_2026')
        svc.prefs['cpu_percent']=0.0
        svc.prefs['gpu_percent']=25.0
        with patch.object(app_server,'PeerStore') as peerstore,patch.object(svc.sessions['tempnet_fablous_2026'].mining,'start',side_effect=RuntimeError('Missing module')):
            peerstore.return_value.peers.return_value=[]
            with self.assertRaisesRegex(RuntimeError,'Missing module'):
                svc.start_miner({'network':'tempnet_fablous_2026','target_mode':'address','address':address})
        self.assertEqual(svc.sessions['tempnet_fablous_2026'].miner_state,'Terminado')
        self.assertIn('Missing module',svc.sessions['tempnet_fablous_2026'].last_error)
        self.assertIn('Missing module',log_archive.log_path(svc.sessions['tempnet_fablous_2026'].active_log_name).read_text('utf8'))
        self.assertEqual(svc.sessions['tempnet_fablous_2026'].mining_run,0)

    def test_new_run_identity_and_old_log_inaccessible_as_active(self):
        from cashminer.wallet.legacy_hd import address_from_secret
        svc=app_server.CashMinerService()
        # Testnet address and session are explicit
        address=address_from_secret(2,'tempnet_fablous_2026')
        svc.prefs['cpu_percent']=0.0
        with patch.object(app_server,'PeerStore') as peerstore,patch.object(svc.sessions['tempnet_fablous_2026'].mining,'start',return_value=['bch_hashscan_cuda.dll']):
            peerstore.return_value.peers.return_value=[]
            svc.start_miner({'network':'tempnet_fablous_2026','target_mode':'address','address':address})
        self.assertEqual(svc.sessions['tempnet_fablous_2026'].mining_run,1)
        self.assertIsNone(svc.sessions['tempnet_fablous_2026'].active_log_name)
        self.assertEqual(svc.state('tempnet_fablous_2026')['mining_run'],1)

if __name__=='__main__':unittest.main()
