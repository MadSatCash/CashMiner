"""Wallet rename/delete regressions. Public test vector; offline, isolated, no real DPAPI."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cashminer.app import server as app_server
from cashminer.wallet.store import WalletStore

WORDS = 'abandon ' * 11 + 'about'


class WalletManagementStore242(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (
            patch('cashminer.wallet.store.protect_seed', side_effect=lambda material, wid: b'fake-dpapi|'+material),
            patch('cashminer.wallet.store.unprotect_seed', side_effect=lambda payload, wid: payload.split(b'|', 1)[1]),
        ):
            p.start(); self.addCleanup(p.stop)
        self.root = Path(self.tmp.name)
        self.store = WalletStore('testnet4', self.root)
        self.first = self.store.create('Primera', mnemonic=WORDS, derivation_path="m/44'/1'/0'")
        self.second = self.store.create('Segunda', mnemonic=WORDS, derivation_path="m/44'/145'/0'")

    def test_rename_does_not_change_seed_address_derivation_or_other_wallet(self):
        wid = self.first['id']
        before = self.store.get(wid)
        vault = self.store._vault_path(wid)
        digest = hashlib.sha256(vault.read_bytes()).digest()
        renamed = self.store.rename(wid, ' Mi billetera 😄 ')
        self.assertEqual(renamed['name'], 'Mi billetera 😄')
        self.assertEqual(renamed['first_address'], before['first_address'])
        self.assertEqual(renamed['derivation_path'], before['derivation_path'])
        self.assertEqual(hashlib.sha256(vault.read_bytes()).digest(), digest)
        self.assertEqual(self.store.get(self.second['id'])['name'], 'Segunda')
        self.assertEqual(self.store.recovery(wid)['mnemonic'], WORDS)

    def test_reject_invalid_rename(self):
        for name in ('', '   ', 'x'*61, 'a\nb', None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.rename(self.first['id'], name)
        with self.assertRaises(ValueError):
            self.store.rename('f'*32, 'Inexistente')
        self.assertEqual(self.store.get(self.first['id'])['name'], 'Primera')

    def test_delete_one_wallet_and_its_local_data_only(self):
        wid = self.first['id']
        keep_id = self.second['id']
        keep_secret = self.store._vault_path(keep_id).read_bytes()
        with self.store.db() as db:
            db.execute('INSERT INTO history(wallet_id,txid,height) VALUES(?,?,?)', (wid, 'ac'*32, 22))
            db.execute('INSERT INTO pending_receipts(wallet_id,spending_txid,destination,amount,created_at) VALUES(?,?,?,?,?)',
                       (wid, 'b1'*32, self.first['address'], 5000, '2026-11-07T00:00:00+00:00'))
            db.execute('INSERT INTO local_transactions(txid,wallet_id,created_at,raw_hex,state) VALUES(?,?,?,?,?)',
                       ('c2'*32, wid, '2026-11-07T00:00:00+00:00', 'aabb', 'test'))
            db.execute('INSERT INTO addresses(wallet_id,branch,idx,address,scripthash) VALUES(?,?,?,?,?)',
                       (wid, 0, 0, self.first['address'], 'd3'*32))
        removed = self.store.delete(wid, 'Primera', self.first['address'])
        self.assertEqual(removed['id'], wid)
        self.assertFalse(self.store._vault_path(wid).exists())
        self.assertEqual([w['id'] for w in self.store.list()], [keep_id])
        self.assertEqual(self.store._vault_path(keep_id).read_bytes(), keep_secret)
        with self.store.db() as db:
            for table in ('addresses','history','utxos','pending_spends','pending_receipts','local_transactions'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table} WHERE wallet_id=?',(wid,)).fetchone()[0], 0)
        # The other network keeps its own independent copy of public addresses.
        main = WalletStore('mainnet', self.root)
        self.assertEqual(main.list(), [])

    def test_stale_confirmation_or_locked_vault_does_not_delete(self):
        wid = self.first['id']
        addr = self.first['address']
        with self.assertRaisesRegex(ValueError, 'cambió'):
            self.store.delete(wid, 'Nombre antiguo', addr)
        with self.assertRaisesRegex(ValueError, 'cambió'):
            self.store.delete(wid, 'Primera', 'bchtest:incorrecta')
        replace = os.replace
        vault = self.store._vault_path(wid)
        def locked(src, dest):
            if Path(src) == vault:
                raise PermissionError('WinError 32: archivo bloqueado')
            return replace(src, dest)
        with patch('cashminer.wallet.store.os.replace', side_effect=locked):
            with self.assertRaises(PermissionError):
                self.store.delete(wid, 'Primera', addr)
        self.assertEqual(self.store.get(wid)['name'], 'Primera')
        self.assertTrue(vault.exists())
        self.assertEqual(len(list(self.store.vault_dir.glob('.delete_pending_*'))), 0)

    def test_sql_failure_restores_encrypted_vault(self):
        wid = self.first['id']
        vault = self.store._vault_path(wid)
        original = vault.read_bytes()
        # Cause a database error after staging the vault file.
        with self.store.db() as db:
            db.execute("CREATE TRIGGER prevent_wallet_delete BEFORE DELETE ON wallets BEGIN SELECT RAISE(ABORT, 'intento bloqueado'); END")
        with self.assertRaises(Exception):
            self.store.delete(wid, 'Primera', self.first['address'])
        self.assertEqual(vault.read_bytes(), original)
        self.assertEqual(self.store.get(wid)['name'], 'Primera')


class WalletManagementHttp242(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (
            patch.dict(os.environ, {'CASHMINER2_DATA_DIR': self.tmp.name}),
            patch.object(app_server, 'PREF_FILE', Path(self.tmp.name)/'settings.json'),
            patch('cashminer.wallet.store.protect_seed', side_effect=lambda material, wid: b'fake-dpapi|'+material),
            patch('cashminer.wallet.store.unprotect_seed', side_effect=lambda payload, wid: payload.split(b'|',1)[1]),
            patch('cashminer.wallet.sync.WalletSync.refresh', return_value=None),
        ):
            p.start(); self.addCleanup(p.stop)
        self.service = app_server.CashMinerService()
        self.server = app_server.LocalServer(self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.service.stop_all()
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def call(self, endpoint, payload=None, error=False):
        headers={'X-CashMiner-Session': self.server.secret}
        if payload is not None: headers['Content-Type']='application/json'
        request=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}{endpoint}',
            data=json.dumps(payload).encode('utf8') if payload is not None else None,
            headers=headers, method='POST' if payload is not None else 'GET')
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if not error: raise
            return json.load(exc)

    def test_rename_and_delete_through_authenticated_api(self):
        self.call('/api/wallet/network',{'network':'testnet4'})
        made = self.call('/api/wallet/import',{'network':'testnet4','name':'Antigua',
            'mnemonic':WORDS,'derivation_path':"m/44'/1'/0'"})
        wid, address = made['id'], made['address']
        failed=self.call('/api/wallet/rename',{'network':'mainnet','id':wid,'name':'Otra'},error=True)
        self.assertIn('red',failed['error'])
        self.call('/api/wallet/rename',{'network':'testnet4','id':wid,'name':'Corregida'})
        self.assertEqual(self.call('/api/state')['wallets'][0]['name'], 'Corregida')
        self.service.wallet_sender.previews['dummy-preview']={'wid':wid,'network':'testnet4','deadline':99999999}
        bad=self.call('/api/wallet/delete',{'network':'testnet4','id':wid,'expected_name':'Antigua','expected_address':address},error=True)
        self.assertIn('cambió',bad['error'])
        gone=self.call('/api/wallet/delete',{'network':'testnet4','id':wid,'expected_name':'Corregida','expected_address':address})
        self.assertEqual(gone['removed'],wid)
        state=self.call('/api/state')
        self.assertEqual(state['wallets'], [])
        self.assertIsNone(state['selected_wallet'])
        self.assertNotIn('dummy-preview',self.service.wallet_sender.previews)
        self.assertEqual(self.service.wallet_sync.wallet_revisions['testnet4'],1)

    def test_ui_has_management_controls_but_no_existing_path_edit(self):
        ui=(Path(__file__).resolve().parents[1]/'ui'/'index.html').read_text('utf-8')
        self.assertIn('id="renameWalletBtn"',ui)
        self.assertIn('id="deleteWalletBtn"',ui)
        self.assertNotIn('id="changeWalletPathBtn"',ui)
