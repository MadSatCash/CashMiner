"""Regresiones de distribución, datos y arquitectura de CashMiner v2.8."""
import hashlib
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cashminer import __version__
from cashminer.config import (canonical_data_home, data_home, found_blocks_home,
    legacy_data_home, legacy_wallets_home, mining_logs_home, modern_wallets_home)
from cashminer.migration import migrate_paths
from cashminer.mining.bridge import prepare_runtime, project_root, SOURCE_FILES

ROOT=Path(__file__).resolve().parents[1]


class ArchitectureV280(unittest.TestCase):
    def test_source_structure_and_version(self):
        self.assertEqual(__version__,'2.17.1')
        for path in ('src/cashminer/app/server.py','src/cashminer/wallet/send.py',
                     'src/cashminer/mining/history.py','src/cashminer/network/peer_store.py',
                     'src/cashminer/platform/log_archive.py','mining_engine/miner.py',
                     'mining_engine/fablous/observer.py'):
            self.assertTrue((ROOT/path).is_file(),path)
        self.assertFalse((ROOT/'src/cashminer2').exists())
        self.assertFalse((ROOT/'engines/tempnet_v6_2').exists())

    def test_runtime_stages_nested_files_and_is_independent(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'CASHMINER_DATA_DIR':td}):
                folder,libraries=prepare_runtime()
                self.assertEqual(folder,Path(td)/'runtime'/'mining_engine')
                for name in SOURCE_FILES:
                    self.assertEqual((folder/name).read_bytes(),(ROOT/'mining_engine'/name).read_bytes())
                self.assertTrue((folder/'miner.py').is_file())
                self.assertIn('bch_hashscan_cuda.dll',libraries)

    def test_legacy_root_retained_until_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('cashminer.config._platform_base', return_value=Path(td)):
                legacy=legacy_data_home();legacy.mkdir()
                (legacy/'wallet_v23').mkdir()
                with patch.dict(os.environ,{},clear=True):
                    self.assertEqual(data_home(),legacy)
                    self.assertEqual(modern_wallets_home(),legacy/'wallet_v23')
                    self.assertEqual(legacy_wallets_home(),legacy/'wallets')
                    self.assertEqual(mining_logs_home(),legacy/'runtime/tempnet_v6_2/logs')
                    self.assertEqual(found_blocks_home(),legacy/'runtime/tempnet_v6_2/found_blocks')
                    canonical=canonical_data_home();canonical.mkdir()
                    self.assertEqual(data_home(),canonical)
                    self.assertEqual(modern_wallets_home(),canonical/'wallets')
                    self.assertEqual(legacy_wallets_home(),canonical/'wallets'/'legacy')

    def test_manual_migration_keeps_original_and_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);old=t/'CashMiner2';new=t/'CashMiner'
            wallet=old/'wallet_v23'/'testnet3';wallet.mkdir(parents=True)
            secret=wallet/'clave.vault';secret.write_bytes(b'INERT-TEST-SECRET-\x00\xff')
            srcdb=wallet/'wallets.sqlite'
            with closing(sqlite3.connect(srcdb)) as db, db:
                db.execute('CREATE TABLE items (k TEXT PRIMARY KEY, n INTEGER)')
                db.execute('INSERT INTO items VALUES (?,?)',('coinbase',42))
            oldlegacy=old/'wallets';oldlegacy.mkdir()
            (oldlegacy/'legacy.pool.json').write_text('{"format":"cashminer2-public-pool-v1"}')
            engine=old/'runtime'/'tempnet_v6_2'
            (engine/'logs').mkdir(parents=True)
            (engine/'logs'/'cashminer.py_26-11-08_01h00m00s.log').write_text('log old')
            (engine/'found_blocks'/'testnet3').mkdir(parents=True)
            (engine/'found_blocks'/'testnet3'/'block.json').write_text('public block')
            (engine/'tempnet_wallet.json').write_bytes(b'LEGACY-PRIVATE-KEY-TEST')
            (engine/'cashminer.py').write_text('replaceable runtime')
            (old/'settings.json').write_text('{"network":"testnet3"}')
            dry=migrate_paths(old,new)
            self.assertFalse(dry['applied']);self.assertFalse(new.exists())
            result=migrate_paths(old,new,apply=True)
            self.assertTrue(result['applied'])
            self.assertTrue(old.is_dir())
            self.assertEqual((new/'wallets/testnet3/clave.vault').read_bytes(),secret.read_bytes())
            with closing(sqlite3.connect(new/'wallets/testnet3/wallets.sqlite')) as db, db:
                self.assertEqual(db.execute('SELECT n FROM items WHERE k="coinbase"').fetchone()[0],42)
            self.assertTrue((new/'wallets/legacy/legacy.pool.json').exists())
            self.assertTrue((new/'wallets/legacy/tempnet_wallet.json').exists())
            self.assertTrue((new/'mining/logs/cashminer.py_26-11-08_01h00m00s.log').exists())
            self.assertTrue((new/'mining/found_blocks/testnet3/block.json').exists())
            self.assertFalse((new/'runtime/tempnet_v6_2/cashminer.py').exists())
            with self.assertRaises(FileExistsError):migrate_paths(old,new,apply=True)

    def test_symlink_rejected_and_destination_not_written(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);old=t/'old';old.mkdir();new=t/'new'
            link=old/'arbitrary_link'
            try:link.symlink_to(t/'missing')
            except (NotImplementedError,OSError):self.skipTest('Symlinks unavailable')
            with self.assertRaisesRegex(RuntimeError,'enlaces simbólicos'):
                migrate_paths(old,new,apply=True)
            self.assertFalse(new.exists())

    def test_native_libraries_match_release_sha256s(self):
        sums=(ROOT/'native/SHA256SUMS.txt').read_text('utf8').splitlines()
        for entry in sums:
            digest,name=entry.split(maxsplit=1)
            native=ROOT/'native'/name
            self.assertTrue(native.is_file(),name)
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(),digest)

    def test_log_reader_accepts_both_legacy_and_modern_names(self):
        from cashminer.platform.log_archive import LOG_NAME
        self.assertIsNotNone(LOG_NAME.fullmatch('cashminer.py_26-11-08_08h00m00s_testnet3_ab1234.log'))
        self.assertIsNotNone(LOG_NAME.fullmatch('miner.py_26-11-08_08h00m00s_testnet3_ab1234.log'))



if __name__=='__main__':unittest.main()
