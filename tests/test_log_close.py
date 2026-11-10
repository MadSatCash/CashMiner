"""Regresión de cierre: no se inicia GPU, no se consultan peers ni red externa."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.platform import log_archive
from cashminer.mining.bridge import MinerController


class DummyProcess:
    def __init__(self, code, text='Inicio nativo\n'):
        self.code = code
        self.stdout = io.StringIO(text)
        self.finished = False
    def poll(self):
        return self.code if self.finished else None
    def wait(self):
        self.finished = True
        return self.code


class MinerCloseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ, {'CASHMINER2_DATA_DIR':self.tmp.name})
        self.env.start();self.addCleanup(self.env.stop)
        self.settings_patch=patch.object(app_server,'PREF_FILE',Path(self.tmp.name)/'settings.json')
        self.settings_patch.start();self.addCleanup(self.settings_patch.stop)
        self.folder=log_archive.logs_dir();self.folder.mkdir(parents=True,exist_ok=True)
        self.name='cashminer.py_26-11-06_04h07m36s.log'
        self.path=self.folder/self.name

    def test_manual_close_appends_after_process_exit_and_preserves_native(self):
        self.path.write_text('Una línea sin salto',encoding='utf-8')
        svc=app_server.CashMinerService()
        svc.sessions['mainnet'].active_log_name=self.name
        svc.miner_exit_for('mainnet',3221225786,'user',False)
        lines=self.path.read_text('utf-8').splitlines()
        self.assertEqual(lines[0],'Una línea sin salto')
        self.assertRegex(lines[1],r'^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] \[CashMiner\] Minería detenida por el usuario\.$')
        self.assertEqual(svc.sessions['mainnet'].miner_state,'Detenido')
        self.assertEqual(svc.sessions['mainnet'].hashrate,0)
        self.assertEqual(log_archive.chunk(self.name,'tail')['text'],self.path.read_text('utf-8'))

    def test_unexpected_exit_is_not_described_as_manual(self):
        self.path.write_text('Encendido\n',encoding='utf-8')
        svc=app_server.CashMinerService();svc.sessions['mainnet'].active_log_name=self.name
        svc.miner_exit_for('mainnet',11,None,False)
        self.assertIn('Proceso minero finalizado inesperadamente (código 11).',self.path.read_text('utf-8'))
        self.assertEqual(svc.sessions['mainnet'].miner_state,'Terminado')

    def test_forced_stop_and_app_close_are_differentiated(self):
        self.path.write_text('Encendido\n',encoding='utf-8')
        svc=app_server.CashMinerService();svc.sessions['mainnet'].active_log_name=self.name
        svc.miner_exit_for('mainnet',-9,'app_close',True)
        self.assertIn('Detención forzada al cerrar CashMiner.',self.path.read_text('utf-8'))

    def test_bridge_passes_correct_stop_reason_only_after_drain(self):
        events=[]
        bridge=MinerController(lambda line:events.append(('line',line)),
                               lambda code,reason,forced:events.append(('exit',code,reason,forced)))
        proc=DummyProcess(3221225786,'A\nB\n');bridge.proc=proc
        self.assertTrue(bridge.request_stop('user'))
        bridge._read_output(proc)
        self.assertEqual(events,[('line','A'),('line','B'),('exit',3221225786,'user',False)])
        self.assertFalse(bridge.running())
        self.assertFalse(bridge.request_stop('user'))

    def test_bridge_unrequested_exit_and_forced_flag(self):
        events=[]
        bridge=MinerController(lambda line:None,lambda *args:events.append(args))
        proc=DummyProcess(21);bridge.proc=proc
        bridge._read_output(proc)
        self.assertEqual(events,[(21,None,False)])
        proc=DummyProcess(-9);bridge.proc=proc
        bridge._stop_reason='user';bridge._forced_stop=True
        bridge._read_output(proc)
        self.assertEqual(events[-1],(-9,'user',True))

    def test_rejects_noncanonical_or_injected_close_event(self):
        self.path.write_text('Inicio\n',encoding='utf-8')
        for value in ('Otro texto','Minería detenida por el usuario.\nBORRAR ARCHIVOS'):
            with self.assertRaises(ValueError):log_archive.append_close_event(self.name,value)
        self.assertEqual(self.path.read_text('utf-8'),'Inicio\n')

if __name__=='__main__':unittest.main()
