"""Windows WinError 32 regression: explicitly close SQLite before replacing a backup.

Uses a test-only connector proxy and synthetic database with no wallet secrets.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import os
import sqlite3
from contextlib import closing
import unittest

from cashminer.wallet.store import WalletStore


class TrackedConnection:
    def __init__(self, real):
        self.real = real
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def backup(self, destination, *args, **kwargs):
        return self.real.backup(destination.real if isinstance(destination, TrackedConnection) else destination, *args, **kwargs)

    def close(self):
        self.real.close()
        self.closed = True


class WindowsBackup241(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'testnet4'
        self.folder.mkdir()
        self.database = self.folder / 'wallets.sqlite'
        with closing(sqlite3.connect(self.database)) as db, db:
            # Pre-v2.4 schema: enough data to simulate a historical Testnet4 wallet.
            db.execute('CREATE TABLE wallets (id TEXT PRIMARY KEY, name TEXT NOT NULL, '
                       'first_address TEXT NOT NULL, account_index INTEGER NOT NULL DEFAULT 0, '
                       "wallet_type TEXT NOT NULL DEFAULT 'hd')")
            db.execute("INSERT INTO wallets (id,name,first_address,account_index) VALUES (?,?,?,?)",
                       ('wallet-1', 'old test wallet', 'bchtest:test-public-placeholder', 2))
        self.before = self.database.read_bytes()
        # Call the exact migration backup without performing the later schema upgrade.
        self.subject = WalletStore.__new__(WalletStore)
        self.subject.dir = self.folder
        self.subject.path = self.database

    def test_windows_style_lock_check_handles_closed_before_replace(self):
        real_connect = sqlite3.connect
        real_replace = os.replace
        tracked = []
        renamed = []

        def connect(*args, **kwargs):
            connection = TrackedConnection(real_connect(*args, **kwargs))
            tracked.append(connection)
            return connection

        def replace(src, dst):
            self.assertEqual(len(tracked), 2)
            self.assertTrue(all(c.closed for c in tracked), 'SQLite handle still open: Windows would raise WinError 32')
            renamed.append((src, dst))
            return real_replace(src, dst)

        with patch('cashminer.wallet.store.sqlite3.connect', side_effect=connect), \
             patch('cashminer.wallet.store.os.replace', side_effect=replace):
            self.subject._backup_before_v24_migration()

        self.assertEqual(len(renamed), 1)
        self.assertEqual(self.database.read_bytes(), self.before)
        backup = self.folder / 'wallets.sqlite.pre_v24.bak'
        self.assertTrue(backup.is_file())
        with closing(sqlite3.connect(backup)) as db, db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT name,account_index FROM wallets').fetchone(), ('old test wallet', 2))
        self.assertEqual(list(self.folder.glob('.pre_v24_*.tmp')), [])

    def test_rename_permission_error_never_alters_original(self):
        with patch('cashminer.wallet.store.os.replace', side_effect=PermissionError('simulated external lock')):
            with self.assertRaisesRegex(PermissionError, 'simulated external lock'):
                self.subject._backup_before_v24_migration()
        self.assertEqual(self.database.read_bytes(), self.before)
        self.assertFalse((self.folder / 'wallets.sqlite.pre_v24.bak').exists())
        self.assertEqual(list(self.folder.glob('.pre_v24_*.tmp')), [])

    def test_migration_preserves_historical_testnet4_coin_type_and_backup(self):
        store = WalletStore('testnet4', Path(self.tmp.name))
        backup = self.folder / 'wallets.sqlite.pre_v24.bak'
        original_snapshot = hashlib.sha256(backup.read_bytes()).hexdigest()
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertEqual(db.execute('SELECT derivation_coin_type FROM wallets WHERE id=?', ('wallet-1',)).fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        WalletStore('testnet4', Path(self.tmp.name))
        self.assertEqual(original_snapshot, hashlib.sha256(backup.read_bytes()).hexdigest())
        with closing(sqlite3.connect(backup)) as db, db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(wallets)')}
            self.assertNotIn('derivation_coin_type', columns)


if __name__ == '__main__':
    unittest.main()
