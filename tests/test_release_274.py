"""Regresión v2.7.5: cierre, navegador administrado y bibliotecas incluidas."""
from __future__ import annotations
import hashlib
import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.mining import bridge as miner_bridge

ROOT=Path(__file__).resolve().parents[1]


class Release273(unittest.TestCase):
    def test_no_pywebview_dependency_or_launcher(self):
        self.assertNotIn('pywebview',(ROOT/'requirements.txt').read_text())
        self.assertNotIn('import webview',(ROOT/'src/cashminer/app/server.py').read_text())
        self.assertFalse((ROOT/'INICIAR_WINDOWS_CON_ICONO.bat').exists())
        self.assertIn('version = "2.17.1"',(ROOT/'pyproject.toml').read_text())

    def test_close_x_stops_server_and_service(self):
        class Process:
            def __init__(self):self.finished=threading.Event();self.terminated=False
            def wait(self,timeout=None):
                if not self.finished.wait(timeout):raise TimeoutError()
                return 0
            def poll(self):return 0 if self.finished.is_set() else None
            def terminate(self):self.terminated=True;self.finished.set()
        class Server:
            def __init__(self):
                self.stopped=threading.Event();self.running=threading.Event();self.closed=threading.Event()
                self.service=SimpleNamespace(stop_all=self.stopped.set)
            def serve_forever(self,**kw):self.running.set();self.closed.wait(3)
            def shutdown(self):self.closed.set()
        process=Process();server=Server()
        with patch.object(app_server,'_start_managed_browser',return_value=(process,None)):
            timer=threading.Timer(.08,process.finished.set);timer.start()
            app_server._run_managed_browser(server,'http://127.0.0.1:9999/')
        self.assertTrue(server.running.is_set())
        self.assertTrue(server.stopped.is_set())
        self.assertTrue(server.closed.is_set())
        self.assertFalse(process.terminated)

    def test_explicit_exit_also_closes_browser_process(self):
        class Process:
            def __init__(self):self.finished=threading.Event();self.terminated=False
            def wait(self,timeout=None):
                if not self.finished.wait(timeout):raise TimeoutError()
                return 0
            def poll(self):return 0 if self.finished.is_set() else None
            def terminate(self):self.terminated=True;self.finished.set()
        class Server:
            def __init__(self):
                self.stopped=threading.Event();self.closed=threading.Event()
                self.service=SimpleNamespace(stop_all=self.stopped.set)
            def serve_forever(self,**kw):self.closed.wait(3)
            def shutdown(self):self.closed.set()
        p=Process();s=Server()
        with patch.object(app_server,'_start_managed_browser',return_value=(p,None)):
            timer=threading.Timer(.08,s.shutdown);timer.start()
            app_server._run_managed_browser(s,'http://127.0.0.1:9999/')
        self.assertTrue(p.terminated)
        self.assertTrue(s.stopped.is_set())

    def test_bundled_dlls_have_expected_windows_header_and_sha256(self):
        import hashlib
        names=miner_bridge.WINDOWS_LIBRARIES
        recorded={}
        for line in (ROOT/'native/SHA256SUMS.txt').read_text().splitlines():
            digest, name=line.split('  ',1)
            recorded[name]=digest
        self.assertEqual(set(recorded),set(names))
        for name in names:
            data=(ROOT/'native'/name).read_bytes()
            self.assertTrue(data.startswith(b'MZ'))
            self.assertGreater(len(data),40_000)
            self.assertEqual(hashlib.sha256(data).hexdigest(),recorded[name])

    def test_only_bundle_is_used_and_stale_runtime_is_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);proj=root/'app';runtime=root/'runtime'
            (proj/'mining_engine').mkdir(parents=True)
            (proj/'native').mkdir()
            runtime.mkdir()
            for name in miner_bridge.SOURCE_FILES:
                (proj/'mining_engine'/name).parent.mkdir(parents=True, exist_ok=True)
                (proj/'mining_engine'/name).write_text('dummy')
            packaged = tuple(sorted(miner_bridge.WINDOWS_LIBRARIES))
            for name in packaged:
                (proj/'native'/name).write_bytes(('packaged ' + name).encode())
            (runtime/'bch_hashscan_opencl.dll').write_bytes(b'legacy stale')
            with patch.object(miner_bridge,'project_root',return_value=proj),\
                 patch.object(miner_bridge,'runtime_folder',return_value=runtime):
                folder, libs=miner_bridge.prepare_runtime()
                self.assertEqual(folder,runtime)
                self.assertEqual(libs,list(packaged))
                for name in packaged:
                    self.assertEqual((runtime/name).read_bytes(),(proj/'native'/name).read_bytes())
                self.assertNotEqual((runtime/'bch_hashscan_opencl.dll').read_bytes(),b'legacy stale')
                self.assertEqual(miner_bridge.native_libraries(),list(packaged))

    def test_missing_package_is_fatal_on_windows_even_if_runtime_has_old_dlls(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj=Path(tmp)/'app';runtime=Path(tmp)/'runtime';runtime.mkdir()
            (proj/'mining_engine').mkdir(parents=True)
            (proj/'native').mkdir()
            for name in miner_bridge.SOURCE_FILES:
                (proj/'mining_engine'/name).parent.mkdir(parents=True, exist_ok=True)
                (proj/'mining_engine'/name).write_text('dummy')
            (runtime/'bch_hashscan_cuda.dll').write_bytes(b'old')
            with patch.object(miner_bridge,'project_root',return_value=proj),\
                 patch.object(miner_bridge,'runtime_folder',return_value=runtime),\
                 patch.object(miner_bridge.os,'name','nt'):
                with self.assertRaisesRegex(FileNotFoundError,'Distribucion incompleta'):
                    miner_bridge.prepare_runtime()

    def test_no_manual_native_import_or_legacy_fallback(self):
        self.assertFalse((ROOT/'scripts/INCORPORAR_DLL_LOCALES.bat').exists())
        self.assertFalse((ROOT/'scripts/incorporar_dll_locales.py').exists())
        self.assertNotIn('local_native_folder', (ROOT/'src/cashminer/mining/bridge.py').read_text())
        self.assertNotIn('import_native_from', (ROOT/'src/cashminer/mining/bridge.py').read_text())
        self.assertNotIn('/api/native/browse',(ROOT/'src/cashminer/app/server.py').read_text())
        self.assertNotIn('importNativeBtn',(ROOT/'ui/index.html').read_text())

if __name__=='__main__':unittest.main()
