"""Real SQLite migrations and RPC backend selection, with isolated synthetic data."""
import gc
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cashminer import migration
from cashminer.mining.bridge import NETWORK_CLI
from cashminer.wallet.store import WalletStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mining_engine'))
import miner as engine


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Migration2171(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(gc.collect)
        self.root = Path(temporary.name)
        self.old = self.root / 'CashMiner2'
        self.new = self.root / 'CashMiner'
        folder = self.old / 'wallet_v23' / 'testnet3'
        folder.mkdir(parents=True)
        self.source = folder / 'wallets.sqlite'
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('CREATE TABLE evidence (key TEXT, value INTEGER)')
            db.execute('INSERT INTO evidence VALUES (?,?)', ('inert fixture', 42))
        self.vault = folder / 'inert.vault'
        self.vault.write_bytes(b'INERT-AUDIT-DATA-NOT-A-PRIVATE-KEY')
        self.before = sha(self.source), sha(self.vault)

    def unchanged(self):
        self.assertEqual((sha(self.source), sha(self.vault)), self.before)

    def test_every_sqlite_handle_is_closed_before_atomic_publish(self):
        real_connect, real_replace = sqlite3.connect, os.replace
        opened = []
        class Tracked(sqlite3.Connection):
            closed = False
            def close(self):
                super().close()
                self.closed = True
        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=Tracked)
            opened.append(connection)
            return connection
        def publish(source, destination):
            self.assertEqual(len(opened), 3)  # source, backup destination, final check
            self.assertTrue(all(c.closed for c in opened), 'Migration still owns open SQLite handles')
            return real_replace(source, destination)
        try:
            with patch.object(migration.sqlite3, 'connect', side_effect=connect), \
                 patch.object(migration.os, 'replace', side_effect=publish):
                result = migration.migrate_paths(self.old, self.new, apply=True)
            self.assertTrue(result['applied'])
            self.unchanged()
            copied = self.new / 'wallets/testnet3/wallets.sqlite'
            with closing(real_connect(copied)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(db.execute('SELECT value FROM evidence').fetchone(), (42,))
            self.assertEqual((self.new / 'wallets/testnet3/inert.vault').read_bytes(), self.vault.read_bytes())
            self.assertEqual(list(self.root.glob('.cashminer-migrate-*')), [])
        finally:
            for connection in opened: connection.close()

    def test_backup_error_closes_handles_and_removes_staging(self):
        real_connect = sqlite3.connect
        opened = []
        class FailedBackup(sqlite3.Connection):
            closed = False
            def backup(self, *args, **kwargs):
                raise sqlite3.DatabaseError('inert backup failure')
            def close(self):
                super().close()
                self.closed = True
        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=FailedBackup)
            opened.append(connection)
            return connection
        try:
            with patch.object(migration.sqlite3, 'connect', side_effect=connect):
                with self.assertRaisesRegex(sqlite3.DatabaseError, 'inert backup failure'):
                    migration.migrate_paths(self.old, self.new, apply=True)
            self.assertTrue(all(c.closed for c in opened))
            self.assertFalse(self.new.exists())
            self.assertEqual(list(self.root.glob('.cashminer-migrate-*')), [])
            self.unchanged()
        finally:
            for connection in opened: connection.close()

    def test_publish_error_preserves_original_and_removes_staging(self):
        with patch.object(migration.os, 'replace', side_effect=PermissionError('inert external lock')):
            with self.assertRaisesRegex(PermissionError, 'inert external lock'):
                migration.migrate_paths(self.old, self.new, apply=True)
        self.assertFalse(self.new.exists())
        self.assertEqual(list(self.root.glob('.cashminer-migrate-*')), [])
        self.unchanged()

    @unittest.skipUnless(os.name == 'nt', 'DPAPI wallet fixture requires Windows')
    def test_migrated_wallet_keeps_vault_seed_and_derivation(self):
        store = WalletStore('testnet4', self.old / 'wallet_v23')
        seed = bytes(range(32))
        wallet = store.create('inert wallet', recovery_hex=seed.hex(), derivation_path="m/44'/1'/2'")
        vault_hash = sha(store._vault_path(wallet['id']))
        migration.migrate_paths(self.old, self.new, apply=True)
        restored = WalletStore('testnet4', self.new / 'wallets')
        self.assertEqual(restored.seed(wallet['id']), seed)
        self.assertEqual(restored.get(wallet['id'])['derivation_path'], "m/44'/1'/2'")
        self.assertEqual(restored.get(wallet['id'])['first_address'], wallet['address'])
        self.assertEqual(sha(restored._vault_path(wallet['id'])), vault_hash)
        self.assertEqual(sha(store._vault_path(wallet['id'])), vault_hash)
        with self.assertRaises(FileExistsError):
            migration.migrate_paths(self.old, self.new, apply=True)
        self.unchanged()

    def test_supplied_launcher_migrates_closed_source_in_new_process(self):
        env = os.environ.copy()
        env.pop('CASHMINER_DATA_DIR', None)
        env.pop('CASHMINER2_DATA_DIR', None)
        env.update(LOCALAPPDATA=str(self.root), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        # The shipped default path under Windows is the one represented above.
        if os.name != 'nt': self.skipTest('Windows default data paths')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/MIGRAR_DATOS.py'), '--apply'],
            env=env, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Migración realizada.', result.stdout)
        self.assertTrue((self.new / 'wallets/testnet3/wallets.sqlite').is_file())
        self.assertEqual(list(self.root.glob('.cashminer-migrate-*')), [])
        self.unchanged()


class RPCBackend2171(unittest.TestCase):
    def dispatch(self, network='regtest', *, cuda=False, opencl=False, cpu=False, gpu=True):
        class StopLoop(BaseException): pass
        solo = engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        solo.c_scanner = None
        solo.cuda_scanner = SimpleNamespace(available=cuda)
        solo.opencl_scanner = SimpleNamespace(available=opencl)
        solo.miner_address = 'inert public fixture'
        solo.script_pubkey = b'\x51'
        solo.invalidator = SimpleNamespace(start=Mock(), stop=Mock())
        solo.fetch_template = Mock(return_value=dict(previousblockhash='00' * 32,
            bits='207fffff', version=4, height=1, curtime=1,
            coinbasevalue=5000000000, transactions=[]))
        solo.mine_template_hybrid_cpu_cuda = Mock(side_effect=StopLoop)
        solo.mine_template_multiprocess = Mock(side_effect=StopLoop)
        with patch.object(engine, 'NETWORK', network), patch.object(engine, 'MINER_MODE', 'rpc'), \
             patch.object(engine, 'CPU_ENABLED', cpu), patch.object(engine, 'GPU_ENABLED', gpu), \
             patch.object(engine, 'USE_C_INTERNAL_THREADS', False), patch.object(engine, 'log'):
            with self.assertRaises(StopLoop): solo.mine_forever()
        return solo

    def test_opencl_without_cuda_or_cpu_reaches_gpu_on_all_six_networks(self):
        for network in NETWORK_CLI.values():
            with self.subTest(network=network):
                solo = self.dispatch(network, opencl=True)
                solo.mine_template_hybrid_cpu_cuda.assert_called_once()
                solo.mine_template_multiprocess.assert_not_called()
                self.assertEqual(solo.mine_template_hybrid_cpu_cuda.call_args.args[0], 1)

    def test_opencl_is_used_even_when_cpu_is_enabled(self):
        solo = self.dispatch(opencl=True, cpu=True)
        solo.mine_template_hybrid_cpu_cuda.assert_called_once()
        solo.mine_template_multiprocess.assert_not_called()

    def test_cuda_and_combined_backends_keep_gpu_dispatch(self):
        for opencl in (False, True):
            with self.subTest(opencl=opencl):
                solo = self.dispatch(cuda=True, opencl=opencl)
                solo.mine_template_hybrid_cpu_cuda.assert_called_once()
                solo.mine_template_multiprocess.assert_not_called()

    def test_disabled_gpu_keeps_cpu_dispatch(self):
        solo = self.dispatch(cuda=True, opencl=True, cpu=True, gpu=False)
        solo.mine_template_multiprocess.assert_called_once()
        solo.mine_template_hybrid_cpu_cuda.assert_not_called()

    def test_unavailable_gpu_keeps_cpu_dispatch(self):
        solo = self.dispatch(cpu=True)
        solo.mine_template_multiprocess.assert_called_once()
        solo.mine_template_hybrid_cpu_cuda.assert_not_called()


if __name__ == '__main__': unittest.main()
