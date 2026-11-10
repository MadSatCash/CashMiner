"""Per-chain SQLite wallet metadata and cached Electrum observations.

No secrets in SQLite. Secrets are protected separately with the current Windows
user's DPAPI context. All network observations are treated as unverified hints.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time

from cashminer.config import data_home, modern_wallets_home, legacy_wallets_home
from cashminer.wallet.crypto import (COIN_TYPE, ORDER, address_for, address_for_legacy,
                                protect_seed, unprotect_seed)
from cashminer.wallet.bip39 import entropy_to_mnemonic, mnemonic_to_entropy, mnemonic_to_seed
from cashminer.wallet.derivation import account_path, parse_account_path


class WalletStore:
    def __init__(self, network: str, root: Path | None = None):
        if network not in COIN_TYPE:
            raise ValueError('Red de billetera desconocida')
        self.network = network
        self.root = Path(root) if root is not None else modern_wallets_home()
        self.dir = self.root / network
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir = self.dir / 'vaults'
        self.vault_dir.mkdir(exist_ok=True)
        self.path = self.dir / 'wallets.sqlite'
        self._backup_before_v24_migration()
        self._backup_before_v277_migration()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS wallets (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, first_address TEXT NOT NULL,
              receive_index INTEGER NOT NULL DEFAULT 0, change_index INTEGER NOT NULL DEFAULT 0,
              scan_state TEXT NOT NULL DEFAULT 'pending', last_sync TEXT, provider TEXT,
              tip_height INTEGER, tip_hash TEXT, error TEXT, created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS unique_wallet_first_address ON wallets(first_address);
            CREATE TABLE IF NOT EXISTS addresses (
              wallet_id TEXT NOT NULL, branch INTEGER NOT NULL, idx INTEGER NOT NULL,
              address TEXT NOT NULL, scripthash TEXT NOT NULL,
              issued INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(wallet_id,branch,idx),
              FOREIGN KEY(wallet_id) REFERENCES wallets(id)
            );
            CREATE INDEX IF NOT EXISTS addr_by_scripthash ON addresses(scripthash);
            CREATE INDEX IF NOT EXISTS addr_by_wallet_address ON addresses(wallet_id,address);
            CREATE TABLE IF NOT EXISTS utxos (
              wallet_id TEXT NOT NULL, txid TEXT NOT NULL, vout INTEGER NOT NULL,
              address TEXT NOT NULL, value INTEGER NOT NULL, height INTEGER NOT NULL,
              coinbase INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(wallet_id,txid,vout),
              FOREIGN KEY(wallet_id) REFERENCES wallets(id)
            );
            CREATE TABLE IF NOT EXISTS history (
              wallet_id TEXT NOT NULL, txid TEXT NOT NULL, height INTEGER NOT NULL,
              PRIMARY KEY(wallet_id,txid)
            );
            CREATE TABLE IF NOT EXISTS servers (
              host TEXT NOT NULL, port INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(host,port)
            );
            CREATE TABLE IF NOT EXISTS pending_spends (
              wallet_id TEXT NOT NULL, source_txid TEXT NOT NULL, source_vout INTEGER NOT NULL,
              spending_txid TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(wallet_id,source_txid,source_vout)
            );
            CREATE TABLE IF NOT EXISTS pending_receipts (
              wallet_id TEXT NOT NULL, spending_txid TEXT NOT NULL,
              destination TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(wallet_id,spending_txid,destination)
            );
            CREATE TABLE IF NOT EXISTS local_transactions (
              txid TEXT PRIMARY KEY, wallet_id TEXT NOT NULL,
              created_at TEXT NOT NULL, raw_hex TEXT NOT NULL, state TEXT NOT NULL
            );
            -- Post-acceptance projections, NOT pre-broadcast reservations.
            -- Kept only until Electrum's histories observe the local TX on
            -- every owned address it affects. No private key or raw TX stored.
            CREATE TABLE IF NOT EXISTS local_broadcast_inputs (
              wallet_id TEXT NOT NULL, broadcast_txid TEXT NOT NULL,
              source_txid TEXT NOT NULL, source_vout INTEGER NOT NULL,
              address TEXT NOT NULL,
              PRIMARY KEY(wallet_id,source_txid,source_vout)
            );
            CREATE TABLE IF NOT EXISTS local_broadcast_outputs (
              wallet_id TEXT NOT NULL, broadcast_txid TEXT NOT NULL,
              vout INTEGER NOT NULL, address TEXT NOT NULL, value INTEGER NOT NULL,
              PRIMARY KEY(wallet_id,broadcast_txid,vout)
            );
            ''')
            # Almacenamiento opcional para certificados Electrum fijados por el
            # usuario. Nunca confiar en certificados autofirmados por defecto.
            server_cols = {r['name'] for r in db.execute('PRAGMA table_info(servers)')}
            if 'tls_cert_sha256' not in server_cols:
                db.execute('ALTER TABLE servers ADD COLUMN tls_cert_sha256 TEXT')
            # Incremental, non-destructive v2.3.2 metadata upgrade. Old rows are HD.
            columns = {r['name'] for r in db.execute('PRAGMA table_info(wallets)')}
            if 'wallet_type' not in columns:
                db.execute("ALTER TABLE wallets ADD COLUMN wallet_type TEXT NOT NULL DEFAULT 'hd'")
            if 'account_index' not in columns:
                db.execute("ALTER TABLE wallets ADD COLUMN account_index INTEGER NOT NULL DEFAULT 0")
            # Existing rows used COIN_TYPE[network] implicitly in v2.3.3.
            # Freeze that historical value per wallet before offering new defaults.
            if 'derivation_coin_type' not in columns:
                db.execute('ALTER TABLE wallets ADD COLUMN derivation_coin_type INTEGER')
            db.execute('UPDATE wallets SET derivation_coin_type=? WHERE derivation_coin_type IS NULL',
                       (COIN_TYPE[self.network],))
            # v2.7.7: the cached Electrum status belongs to each address, never
            # to a shared cross-network database. Unknown legacy rows are scanned
            # once; a matching status thereafter allows zero history/UTXO RPCs.
            address_cols={r['name'] for r in db.execute('PRAGMA table_info(addresses)')}
            if 'electrum_status' not in address_cols:
                db.execute('ALTER TABLE addresses ADD COLUMN electrum_status TEXT')
            if 'status_known' not in address_cols:
                db.execute('ALTER TABLE addresses ADD COLUMN status_known INTEGER NOT NULL DEFAULT 0')
            db.execute('''CREATE TABLE IF NOT EXISTS address_history (
                wallet_id TEXT NOT NULL, branch INTEGER NOT NULL, idx INTEGER NOT NULL,
                txid TEXT NOT NULL, height INTEGER NOT NULL,
                PRIMARY KEY(wallet_id,branch,idx,txid),
                FOREIGN KEY(wallet_id) REFERENCES wallets(id)
            )''')
            # Old pending_spends/pending_receipts tables are deliberately left
            # untouched for non-destructive migration, but no longer affect BCH
            # balances or the choice of inputs. Only Electrum UTXO state does.


    def _backup_before_v277_migration(self):
        """Preserve a consistent pre-incremental DB once, without touching vaults."""
        if not self.path.is_file():return
        backup=self.dir/'wallets.sqlite.pre_v277.bak'
        if backup.exists():return
        with closing(sqlite3.connect(self.path,timeout=12)) as source:
            columns={r[1] for r in source.execute('PRAGMA table_info(addresses)')}
            if not columns or 'status_known' in columns:return
            fd,tmp=tempfile.mkstemp(prefix='.pre_v277_',suffix='.tmp',dir=self.dir)
            os.close(fd)
            try:
                with closing(sqlite3.connect(tmp,timeout=12)) as dest:
                    source.backup(dest)
                    dest.commit()
            except Exception:
                if os.path.exists(tmp):os.unlink(tmp)
                raise
        try:os.replace(tmp,backup)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def _backup_before_v24_migration(self):
        """Create a single consistent SQLite backup before the v2.4 schema upgrade.

        sqlite3.Connection.__exit__ commits/rolls back but DOES NOT CLOSE the
        connection. On Windows the open destination handle prevents os.replace;
        use closing() for both handles before renaming the temporary backup.
        A failure aborts the migration without touching the original database.
        """
        if not self.path.is_file():
            return
        backup = self.dir / 'wallets.sqlite.pre_v24.bak'
        with closing(sqlite3.connect(self.path, timeout=12)) as source:
            columns = {row[1] for row in source.execute('PRAGMA table_info(wallets)')}
            if not columns or 'derivation_coin_type' in columns or backup.exists():
                return
            fd, tmp = tempfile.mkstemp(prefix='.pre_v24_', suffix='.tmp', dir=self.dir)
            os.close(fd)
            try:
                with closing(sqlite3.connect(tmp, timeout=12)) as destination:
                    source.backup(destination)
                    destination.commit()
            except Exception:
                # The destination handle is already closed; do not mask the backup error.
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        # Source and destination are now explicitly closed on every platform.
        try:
            os.replace(tmp, backup)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=12)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=12000')
            db.execute('PRAGMA foreign_keys=ON')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _vault_path(self, wid: str):
        if len(wid) != 32 or any(c not in '0123456789abcdef' for c in wid):
            raise ValueError('Identificador de billetera inválido')
        return self.vault_dir / (wid + '.json')

    def _write_vault(self, wid: str, material: bytes, mode: str = 'raw-bip32'):
        if mode not in ('raw-bip32', 'bip39-english', 'legacy-compressed', 'legacy-uncompressed'):
            raise ValueError('Formato de respaldo inválido')
        envelope = {'format': 'cashminer-v23-dpapi', 'network': self.network,
                    'id': wid, 'seed_mode': mode,
                    'blob': base64.b64encode(protect_seed(material, wid)).decode('ascii')}
        fd, temp = tempfile.mkstemp(prefix='.vault-', dir=self.vault_dir)
        try:
            if os.name == 'posix': os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                json.dump(envelope, file)
                file.flush(); os.fsync(file.fileno())
            os.replace(temp, self._vault_path(wid))
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def _read_material(self, wid: str) -> tuple[bytes, str]:
        envelope = json.loads(self._vault_path(wid).read_text('utf-8'))
        if (envelope.get('format') != 'cashminer-v23-dpapi' or
                envelope.get('network') != self.network or envelope.get('id') != wid):
            raise ValueError('Almacén de claves incorrecto o de otra red')
        mode = envelope.get('seed_mode', 'raw-bip32')  # Compatibility with interim v2.3 vaults.
        if mode not in ('raw-bip32', 'bip39-english', 'legacy-compressed', 'legacy-uncompressed'):
            raise ValueError('Formato de semilla no reconocido')
        material = unprotect_seed(base64.b64decode(envelope['blob'], validate=True), wid)
        if (mode == 'raw-bip32' and len(material) not in (32, 64)) or (
                mode == 'bip39-english' and len(material) not in (16, 20, 24, 28, 32)) or (
                mode.startswith('legacy-') and not (len(material) == 32 and 0 < int.from_bytes(material, 'big') < ORDER)):
            raise ValueError('La semilla recuperada tiene tamaño inesperado')
        return material, mode

    def seed(self, wid: str) -> bytes:
        material, mode = self._read_material(wid)
        if mode.startswith('legacy-'):
            raise ValueError('Una clave privada individual no es una semilla HD')
        seed = (mnemonic_to_seed(entropy_to_mnemonic(material)) if mode == 'bip39-english'
                else material)
        wallet = self.get(wid)
        if address_for(seed, self.network, 0, 0, wallet['account_index'], wallet['derivation_coin_type']) != wallet['first_address']:
            raise ValueError('La semilla no coincide con la billetera')
        return seed

    def legacy_key(self, wid: str) -> tuple[int, bool]:
        material, mode = self._read_material(wid)
        if mode not in ('legacy-compressed', 'legacy-uncompressed'):
            raise ValueError('La billetera no contiene una clave Legacy')
        compressed = mode == 'legacy-compressed'
        scalar = int.from_bytes(material, 'big')
        if address_for_legacy(scalar, self.network, compressed) != self.get(wid)['first_address']:
            raise ValueError('La clave privada no coincide con la dirección de la billetera')
        return scalar, compressed

    def recovery(self, wid: str) -> dict:
        # Never return a secret before checking its public address.
        material, mode = self._read_material(wid)
        account = self.get(wid)['account_index']
        if mode.startswith('legacy-'):
            self.legacy_key(wid)
            return {'kind': 'legacy-hex', 'private_key_hex': material.hex(),
                    'compressed': mode == 'legacy-compressed'}
        self.seed(wid)
        if mode == 'bip39-english':
            return {'kind': 'bip39', 'mnemonic': entropy_to_mnemonic(material), 'account_index': account,
                    'derivation_path': self.get(wid)['derivation_path']}
        return {'kind': 'raw-bip32', 'seed_hex': material.hex(), 'account_index': account,
                'derivation_path': self.get(wid)['derivation_path']}

    def legacy_candidates(self, private_hex: str) -> list[dict]:
        if not isinstance(private_hex, str):
            raise ValueError('Clave privada inválida')
        raw = private_hex.strip()
        if raw.lower().startswith('0x'): raw = raw[2:]
        if len(raw) != 64 or any(c not in '0123456789abcdefABCDEF' for c in raw):
            raise ValueError('La clave Legacy debe contener 64 caracteres hexadecimales')
        scalar = int(raw, 16)
        if not 0 < scalar < ORDER:
            raise ValueError('Clave privada fuera del rango secp256k1')
        return [{'compressed': True, 'label': 'Comprimida',
                 'address': address_for_legacy(scalar, self.network, True)},
                {'compressed': False, 'label': 'Sin comprimir',
                 'address': address_for_legacy(scalar, self.network, False)}]


    def create(self, name: str, recovery_hex: str | None = None,
               mnemonic: str | None = None, legacy_hex: str | None = None,
               legacy_compressed: bool = True, account_index: int = 0,
               new_type: str = 'bip39', seed_bytes: int = 32,
               expected_address: str | None = None, derivation_path: str | None = None,
               bip39_words: int = 12):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('Escribí un nombre de hasta 60 caracteres')
        if type(account_index) is not int or not 0 <= account_index <= 1000:
            raise ValueError('La cuenta HD debe estar entre 0 y 1000')
        if sum(value is not None for value in (recovery_hex, mnemonic, legacy_hex)) > 1:
            raise ValueError('Indicá una sola forma de recuperación')
        if new_type not in ('bip39', 'raw-bip32', 'legacy-hex'):
            raise ValueError('Tipo de billetera desconocido')
        if seed_bytes not in (32, 64):
            raise ValueError('Sólo se generan semillas HD de 32 o 64 bytes')
        if new_type == 'bip39' and (type(bip39_words) is not int or bip39_words not in (12, 15, 18, 21, 24)):
            raise ValueError('BIP39 requiere 12, 15, 18, 21 o 24 palabras')
        if type(legacy_compressed) is not bool:
            raise ValueError('Selección de clave comprimida inválida')
        generated = recovery_hex is None and mnemonic is None and legacy_hex is None
        if derivation_path is not None:
            coin_type, parsed_account = parse_account_path(derivation_path)
            if account_index not in (0, parsed_account):
                raise ValueError('Cuenta HD y ruta de derivación contradictorias')
            account_index = parsed_account
        else:
            coin_type = COIN_TYPE[self.network]  # Compatible with prior direct API usage.
        if legacy_hex is not None or (generated and new_type == 'legacy-hex'):
            if derivation_path is not None:
                raise ValueError('Una clave Legacy no admite ruta HD')
            if account_index:
                raise ValueError('Una clave Legacy no tiene cuentas HD')
            if generated:
                scalar = secrets.randbelow(ORDER - 1) + 1
                material = scalar.to_bytes(32, 'big')
            else:
                material = bytes.fromhex(legacy_hex.strip()[2:] if legacy_hex.strip().lower().startswith('0x') else legacy_hex.strip()) if isinstance(legacy_hex, str) else b''
                if len(material) != 32 or not 0 < int.from_bytes(material, 'big') < ORDER:
                    raise ValueError('Clave privada Legacy inválida')
                scalar = int.from_bytes(material, 'big')
            mode = 'legacy-compressed' if legacy_compressed else 'legacy-uncompressed'
            wallet_type = mode
            first = address_for_legacy(scalar, self.network, legacy_compressed)
        else:
            if mnemonic is not None:
                material = mnemonic_to_entropy(mnemonic)
                mode = 'bip39-english'
            elif recovery_hex is not None:
                if not isinstance(recovery_hex, str) or len(recovery_hex.strip()) not in (64, 128):
                    raise ValueError('La semilla HD requiere 64 o 128 caracteres hexadecimales')
                try: material = bytes.fromhex(recovery_hex.strip())
                except ValueError as exc: raise ValueError('Semilla hexadecimal inválida') from exc
                mode = 'raw-bip32'
            elif new_type == 'raw-bip32':
                material = secrets.token_bytes(seed_bytes)
                mode = 'raw-bip32'
            else:
                # BIP39: 12/15/18/21/24 palabras = 16/20/24/28/32 bytes de entropía.
                material = secrets.token_bytes(bip39_words * 4 // 3)
                mode = 'bip39-english'
            seed = (mnemonic_to_seed(entropy_to_mnemonic(material)) if mode == 'bip39-english'
                    else material)
            wallet_type = mode
            first = address_for(seed, self.network, 0, 0, account_index, coin_type)
        if legacy_hex is not None and expected_address is None:
            raise ValueError('Antes de importar una clave Legacy, confirmá la dirección pública calculada')
        if expected_address is not None and expected_address != first:
            raise ValueError('La dirección calculada no coincide con la dirección esperada')
        wid = secrets.token_hex(16)
        self._write_vault(wid, material, mode)
        try:
            with self.db() as db:
                db.execute('INSERT INTO wallets(id,name,first_address,created_at,wallet_type,account_index,derivation_coin_type) '
                           'VALUES(?,?,?,?,?,?,?)',
                           (wid, name.strip(), first, datetime.now(timezone.utc).isoformat(),
                            wallet_type, account_index, coin_type if not mode.startswith('legacy-') else COIN_TYPE[self.network]))
        except sqlite3.IntegrityError as exc:
            self._vault_path(wid).unlink(missing_ok=True)
            raise ValueError('Esta billetera ya existe en esta red') from exc
        except Exception:
            self._vault_path(wid).unlink(missing_ok=True)
            raise
        result = {'id': wid, 'name': name.strip(), 'network': self.network,
                  'kind': 'legacy' if mode.startswith('legacy-') else 'hd',
                  'wallet_type': wallet_type, 'address': first,
                  'account_index': account_index,
                  'derivation_path': None if mode.startswith('legacy-') else account_path(coin_type,account_index)}
        if generated:
            if mode == 'bip39-english':
                result['recovery_phrase'] = entropy_to_mnemonic(material)
            elif mode == 'raw-bip32':
                result['seed_hex'] = material.hex()
            else:
                result['private_key_hex'] = material.hex()
        return result

    def get(self, wid: str):
        self._vault_path(wid)  # validate the ID before DB query
        with self.db() as db:
            row = db.execute('SELECT * FROM wallets WHERE id=?', (wid,)).fetchone()
        if row is None: raise ValueError('Billetera inexistente')
        wallet=dict(row)
        wallet['derivation_path']=(None if wallet['wallet_type'].startswith('legacy-') else
                                   account_path(wallet['derivation_coin_type'],wallet['account_index']))
        return wallet

    def list(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM wallets ORDER BY created_at,name').fetchall()
            result = []
            for row in rows:
                wallet = dict(row)
                wallet['derivation_path']=(None if wallet['wallet_type'].startswith('legacy-') else
                                           account_path(wallet['derivation_coin_type'],wallet['account_index']))
                utxos = db.execute('SELECT txid,vout,value,height,coinbase,tokens FROM utxos WHERE wallet_id=?',
                                   (wallet['id'],)).fetchall()
                known = wallet['last_sync'] is not None
                tip = wallet['tip_height'] or 0
                spendable = sum(u['value'] for u in utxos
                                if not u['tokens'] and
                                (not u['coinbase'] or (u['height'] > 0 and tip-u['height']+1 >= 100)))
                immature = sum(u['value'] for u in utxos if u['coinbase'] and u['height'] > 0
                               and tip-u['height']+1 < 100)
                unconfirmed = sum(u['value'] for u in utxos if u['height'] <= 0)
                receive_used_count=db.execute(
                    'SELECT COUNT(*) FROM addresses WHERE wallet_id=? AND branch=0 AND used=1',
                    (wallet['id'],)).fetchone()[0]
                wallet.update({'kind':'legacy' if wallet['wallet_type'].startswith('legacy-') else 'hd',
                                'address':wallet['first_address'],
                               'available_sats':spendable if known else None,
                               'immature_sats':immature if known else None,
                               'unconfirmed_sats':unconfirmed if known else None,
                               'outgoing_reserved_sats':0 if known else None,
                               'total_sats':sum(u['value'] for u in utxos) if known else None,
                               'utxo_count':len(utxos) if known else None,
                               'receive_used_count':receive_used_count,
                               'token_locked_sats':sum(u['value'] for u in utxos if u['tokens']) if known else None})
                result.append(wallet)
        return result

    def total_unique(self, wallets: list[dict]) -> dict:
        """Network totals from unique outpoints, including the spendable subtotal.

        A wallet imported more than once may observe the same UTXO. Count it
        once, and use the same coinbase maturity/token rules as ``list()``.
        If overlapping snapshots disagree, never overstate spendable funds;
        leave the aggregate marked as pending verification.
        """
        known={w['id'] for w in wallets if w.get('available_sats') is not None}
        complete=all(w.get('available_sats') is not None and w.get('scan_state')=='synced'
                     for w in wallets)
        heights={w['id']:int(w.get('tip_height') or 0) for w in wallets}
        seen={}
        if known:
            with self.db() as db:
                ids=sorted(known)
                placeholders=','.join('?' for _ in ids)
                rows=db.execute('SELECT wallet_id,txid,vout,value,height,coinbase,tokens '
                                'FROM utxos WHERE wallet_id IN ('+placeholders+')',ids)
                for row in rows:
                    outpoint=(row['txid'],row['vout'])
                    value=int(row['value'])
                    height=int(row['height'])
                    tip=heights[row['wallet_id']]
                    spendable=(not row['tokens'] and
                               (not row['coinbase'] or (height>0 and tip-height+1>=100)))
                    if outpoint in seen:
                        original_value,original_spendable=seen[outpoint]
                        if value!=original_value or spendable!=original_spendable:
                            complete=False
                        # A contradictory observation is not safe to count
                        # as available, regardless of which arrived first.
                        seen[outpoint]=(original_value,original_spendable and
                                        spendable and value==original_value)
                    else:
                        seen[outpoint]=(value,spendable)
        return {'total_sats':sum(value for value,_ in seen.values()),
                'available_sats':sum(value for value,spendable in seen.values() if spendable),
                'complete':bool(complete),'wallets_known':len(known),
                'wallets_total':len(wallets)}

    def rename(self, wid: str, name: str) -> dict:
        """Only the local display name changes; no keys, paths or addresses."""
        self._vault_path(wid)  # Reject malformed identifiers.
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('Escribí un nombre de entre 1 y 60 caracteres')
        new_name = name.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in new_name):
            raise ValueError('El nombre contiene caracteres de control')
        with self.db() as db:
            result = db.execute('UPDATE wallets SET name=? WHERE id=?', (new_name, wid))
            if result.rowcount != 1:
                raise ValueError('Billetera inexistente')
        return self.get(wid)

    def delete(self, wid: str, expected_name: str, expected_address: str) -> dict:
        """Forget one local wallet, including its DPAPI vault and cached records.

        Stage the encrypted vault first, so a locked file never causes partial
        database deletion. Restore it if the SQLite transaction fails. This is
        a logical deletion, not secure erasure of old backups or disk blocks.
        """
        vault = self._vault_path(wid)
        staged = None
        removed = None
        committed = False
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM wallets WHERE id=?', (wid,)).fetchone()
                if row is None:
                    raise ValueError('Billetera inexistente')
                if (not isinstance(expected_name, str) or not isinstance(expected_address, str)
                        or row['name'] != expected_name or row['first_address'] != expected_address):
                    raise ValueError('La billetera cambió. Actualizá la pantalla antes de eliminarla')
                if not vault.is_file():
                    raise ValueError('No se encontró el respaldo cifrado; no se eliminó la billetera')
                staged = self.vault_dir / ('.delete_pending_' + wid + '_' + secrets.token_hex(8) + '.json')
                os.replace(vault, staged)
                for table in ('addresses', 'utxos', 'history', 'address_history', 'pending_spends',
                              'pending_receipts', 'local_transactions'):
                    db.execute(f'DELETE FROM {table} WHERE wallet_id=?', (wid,))
                db.execute('DELETE FROM wallets WHERE id=?', (wid,))
                removed = {'id': wid, 'name': row['name'], 'first_address': row['first_address']}
            committed = True
        except Exception:
            if staged is not None and staged.exists() and not committed:
                try:
                    os.replace(staged, vault)
                except OSError as restore_exc:
                    raise RuntimeError('No se pudo restaurar el vault cifrado tras el fallo; conservá el archivo de recuperación local') from restore_exc
            raise
        # Database commit succeeded. Never resurrect a deleted key in the UI.
        try:
            staged.unlink()
        except OSError:
            # Report the residual encrypted file, while allowing the service to
            # clear the deleted wallet from its selection and cached previews.
            removed['cleanup_warning'] = 'Quedó un vault cifrado pendiente de borrar en el almacenamiento local'
        return removed

    def issue_receive(self, wid: str):
        """Return the first never-used receive address; opening the dialog is not issuance.

        Previously exposed HD addresses stay monitored, even if this selects
        an earlier unused index after an upgrade. `used` is sticky: confirmed
        or mempool history is sufficient to advance to the next address.
        """
        wallet = self.get(wid)
        from cashminer.wallet.crypto import script_hash
        if wallet['wallet_type'].startswith('legacy-'):
            self.legacy_key(wid)  # Verify the original address before exposing it.
            address = wallet['first_address']
            with self.db() as db:
                db.execute('INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued) '
                           'VALUES(?,?,?,?,?,1) ON CONFLICT(wallet_id,branch,idx) DO UPDATE SET issued=1',
                           (wid,0,0,address,script_hash(address,self.network)))
            return {'address':address, 'index':0, 'network':self.network, 'reused':True}
        seed = self.seed(wid)
        with self.db() as db:
            # Concurrent Receive requests must not race with one another.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT receive_index FROM wallets WHERE id=?',(wid,)).fetchone()
            if row is None: raise ValueError('Billetera inexistente')
            known = {r['idx']:r for r in db.execute(
                'SELECT idx,address,scripthash,used FROM addresses '
                'WHERE wallet_id=? AND branch=0 ORDER BY idx',(wid,))}
            idx = 0
            # Do not choose a formerly-used address, even if its balance is now zero.
            while idx in known and known[idx]['used']:
                idx += 1
            if idx >= 100000: raise ValueError('Límite de direcciones de recepción')
            address = address_for(seed,self.network,0,idx,
                                  wallet['account_index'],wallet['derivation_coin_type'])
            sh = script_hash(address,self.network)
            previous = known.get(idx)
            if previous and (previous['address'] != address or previous['scripthash'] != sh):
                raise ValueError('Dirección HD registrada no coincide con la derivación')
            db.execute('INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued) '
                       'VALUES(?,?,?,?,?,1) ON CONFLICT(wallet_id,branch,idx) DO UPDATE SET issued=1',
                       (wid,0,idx,address,sh))
            # Preserve a higher legacy issuance watermark for gap discovery.
            if row['receive_index'] <= idx:
                db.execute('UPDATE wallets SET receive_index=? WHERE id=?',(idx+1,wid))
        return {'address':address, 'index':idx, 'network':self.network,
                'reused':bool(previous)}

    def addresses(self,wid: str):
        self.get(wid)
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM addresses WHERE wallet_id=?',(wid,))]

    def address_page(self, wid: str, page: int = 1, page_size: int = 50) -> dict:
        """Read-only, paged address view from the existing network-local SQLite cache.

        Does not derive keys, issue addresses, or contact Electrum. All rows and
        totals are read inside a single transaction/snapshot. Page-sized UTXO
        lookup avoids loading the whole wallet when it has many addresses.
        """
        self._vault_path(wid)  # Same wallet-id validation as every other operation.
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise ValueError('Página de direcciones inválida')
        if page_size != 50:
            raise ValueError('Tamaño de página inválido')
        with self.db() as db:
            wallet = db.execute('SELECT id,wallet_type,tip_height,last_sync FROM wallets WHERE id=?',
                                (wid,)).fetchone()
            if wallet is None:
                raise ValueError('Billetera inexistente')
            count = db.execute('SELECT COUNT(*) FROM addresses WHERE wallet_id=?',(wid,)).fetchone()[0]
            branches = {int(row['branch']):row['n'] for row in db.execute(
                'SELECT branch,COUNT(*) AS n FROM addresses WHERE wallet_id=? GROUP BY branch',(wid,))}
            rows = [dict(row) for row in db.execute("""
                SELECT branch,idx,address,issued,used,status_known FROM addresses
                WHERE wallet_id=? ORDER BY branch,idx LIMIT ? OFFSET ?""",
                (wid, page_size, (page-1)*page_size))]
            sums = {}
            if rows:
                addresses = [row['address'] for row in rows]
                placeholders = ','.join('?' for _ in addresses)
                for utxo in db.execute("""SELECT address,value,height,coinbase,tokens FROM utxos
                    WHERE wallet_id=? AND address IN ("""+placeholders+")", (wid,*addresses)):
                    addr=utxo['address']
                    summary=sums.setdefault(addr,{'total_sats':0,'available_sats':0,
                                                  'immature_sats':0,'token_locked_sats':0})
                    value=int(utxo['value'])
                    height=int(utxo['height'])
                    coinbase=bool(utxo['coinbase'])
                    summary['total_sats']+=value
                    if coinbase and height>0 and int(wallet['tip_height'] or 0)-height+1<100:
                        summary['immature_sats']+=value
                    if utxo['tokens']:
                        summary['token_locked_sats']+=value
                    elif not coinbase or (height>0 and int(wallet['tip_height'] or 0)-height+1>=100):
                        summary['available_sats']+=value
            result=[]
            for row in rows:
                status_known=bool(row['status_known']) and wallet['last_sync'] is not None
                amounts=sums.get(row['address'],{})
                result.append({'branch':row['branch'],'index':row['idx'],
                               'address':row['address'],'issued':bool(row['issued']),
                               'used':bool(row['used']), 'status_known':status_known,
                               'total_sats':amounts.get('total_sats',0) if status_known else None,
                               'available_sats':amounts.get('available_sats',0) if status_known else None,
                               'immature_sats':amounts.get('immature_sats',0) if status_known else None,
                               'token_locked_sats':amounts.get('token_locked_sats',0) if status_known else None})
        return {'wallet_id':wid, 'network':self.network, 'page':page, 'page_size':page_size,
                'total':count, 'pages':max(1,(count+page_size-1)//page_size),
                'counts':{'receive':branches.get(0,0),'change':branches.get(1,0)},
                'addresses':result}

    def apply_snapshot(self,wid: str, address_rows: list[dict], outputs: list[dict],
                       histories: list[dict], tip_height: int, tip_hash: str, provider: str):
        """Replace a *complete* wallet observation in one transaction (no partial balances)."""
        if not 0 <= tip_height < 2**32 or len(tip_hash) != 64:
            raise ValueError('Referencia de cadena inválida')
        seen = {(u['txid'],u['vout']) for u in outputs}
        if len(seen) != len(outputs):
            # The same UTXO can be seen via multiple monitored addresses only
            # if upstream supplied an inconsistent mapping; fail closed.
            raise ValueError('UTXO duplicado en el snapshot')
        with self.db() as db:
            for a in address_rows:
                db.execute('INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued,used) '
                           'VALUES(?,?,?,?,?,?,?) ON CONFLICT(wallet_id,branch,idx) DO UPDATE SET '
                           'used=MAX(used,excluded.used),issued=MAX(issued,excluded.issued)',
                           (wid,a['branch'],a['idx'],a['address'],a['scripthash'],
                            int(a.get('issued',0)),int(a.get('used',0))))
            db.execute('DELETE FROM utxos WHERE wallet_id=?',(wid,))
            db.executemany('INSERT INTO utxos(wallet_id,txid,vout,address,value,height,coinbase,tokens) '
                           'VALUES(?,?,?,?,?,?,?,?)',
                           [(wid,u['txid'],u['vout'],u['address'],u['value'],u['height'],
                             int(u.get('coinbase',0)),int(u.get('tokens',0))) for u in outputs])
            # Once an input disappears from a complete Electrum UTXO observation,
            # its local spending reservation is no longer necessary.
            for pending in db.execute('SELECT source_txid,source_vout FROM pending_spends WHERE wallet_id=?',(wid,)).fetchall():
                if (pending['source_txid'],pending['source_vout']) not in seen:
                    db.execute('DELETE FROM pending_spends WHERE wallet_id=? AND source_txid=? AND source_vout=?',
                               (wid,pending['source_txid'],pending['source_vout']))
            known_txids={h['txid'] for h in histories}
            for pending in db.execute('SELECT spending_txid,destination FROM pending_receipts WHERE wallet_id=?',(wid,)).fetchall():
                if pending['spending_txid'] in known_txids:
                    db.execute('DELETE FROM pending_receipts WHERE wallet_id=? AND spending_txid=? AND destination=?',
                               (wid,pending['spending_txid'],pending['destination']))
            db.execute('DELETE FROM history WHERE wallet_id=?',(wid,))
            db.executemany('INSERT OR REPLACE INTO history(wallet_id,txid,height) VALUES(?,?,?)',
                           [(wid,h['txid'],h['height']) for h in histories])
            db.execute("UPDATE wallets SET scan_state='synced',last_sync=?,provider=?,tip_height=?,tip_hash=?,error=NULL WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(),provider,tip_height,tip_hash,wid))
            db.commit()

    def apply_incremental(self, wid: str, address_rows: list[dict], changed: list[dict],
                          tip_height: int, tip_hash: str, provider: str):
        # Publish all queried address changes atomically. Unchanged addresses
        # keep their UTXOs and history; no full-wallet replacement is needed.
        if not 0 <= tip_height < 2**32 or len(tip_hash)!=64:
            raise ValueError('Referencia de cadena inválida')
        distinct={(a['branch'],a['idx']) for a in address_rows}
        if len(distinct)!=len(address_rows):
            raise ValueError('Direcciones duplicadas en sincronización')
        changes={(a['branch'],a['idx']):a for a in changed}
        if not set(changes).issubset(distinct):
            raise ValueError('Actualización de una dirección no descubierta')
        with self.db() as db:
            if db.execute('SELECT 1 FROM wallets WHERE id=?',(wid,)).fetchone() is None:
                raise ValueError('Billetera eliminada')
            for a in address_rows:
                db.execute('''INSERT INTO addresses
                    (wallet_id,branch,idx,address,scripthash,issued,used,electrum_status,status_known)
                    VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(wallet_id,branch,idx) DO UPDATE SET
                    used=MAX(addresses.used,excluded.used),
                    issued=MAX(addresses.issued,excluded.issued),
                    electrum_status=excluded.electrum_status,status_known=1''',
                    (wid,a['branch'],a['idx'],a['address'],a['scripthash'],
                     int(a.get('issued',0)),int(a.get('used',0)),a['electrum_status']))
            for (branch,idx), change in changes.items():
                address=change['address']
                outputs=change['utxos']
                if len({(u['txid'],u['vout']) for u in outputs})!=len(outputs):
                    raise ValueError('UTXO duplicado para una dirección')
                db.execute('DELETE FROM utxos WHERE wallet_id=? AND address=?',(wid,address))
                db.executemany('''INSERT INTO utxos
                    (wallet_id,txid,vout,address,value,height,coinbase,tokens)
                    VALUES(?,?,?,?,?,?,?,?)''',
                    [(wid,u['txid'],u['vout'],address,u['value'],u['height'],
                      int(u['coinbase']),int(u['tokens'])) for u in outputs])
                db.execute('DELETE FROM address_history WHERE wallet_id=? AND branch=? AND idx=?',
                           (wid,branch,idx))
                db.executemany('''INSERT INTO address_history
                    (wallet_id,branch,idx,txid,height) VALUES(?,?,?,?,?)''',
                    [(wid,branch,idx,h['txid'],h['height']) for h in change['history']])
            # Wallet-wide display history is a derived, compact index. A TXID
            # shared by multiple owned addresses is represented exactly once.
            if changed:
                db.execute('DELETE FROM history WHERE wallet_id=?',(wid,))
                db.execute('''INSERT INTO history(wallet_id,txid,height)
                    SELECT wallet_id,txid,MAX(height) FROM address_history
                    WHERE wallet_id=? GROUP BY wallet_id,txid''',(wid,))
            # A scan may have started before our successful broadcast, or this
            # Electrum server may not yet have seen the transaction. Preserve
            # post-ACK local spent/owned-output projections in either case.
            # Reconcile them away only when *all* affected owned addresses have
            # independently reported the broadcast TXID in their histories.
            self._reconcile_local_broadcasts(db,wid)
            db.execute("UPDATE wallets SET scan_state='synced',last_sync=?,provider=?,tip_height=?,tip_hash=?,error=NULL WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(),provider,tip_height,tip_hash,wid))
            db.commit()

    @staticmethod
    def _reconcile_local_broadcasts(db, wid: str):
        spent=[dict(r) for r in db.execute(
            'SELECT * FROM local_broadcast_inputs WHERE wallet_id=?',(wid,))]
        credits=[dict(r) for r in db.execute(
            'SELECT * FROM local_broadcast_outputs WHERE wallet_id=?',(wid,))]
        by_tx={}
        for row in spent:
            by_tx.setdefault(row['broadcast_txid'],{'inputs':[],'outputs':[]})['inputs'].append(row)
        for row in credits:
            by_tx.setdefault(row['broadcast_txid'],{'inputs':[],'outputs':[]})['outputs'].append(row)
        def address_saw_tx(address, txid):
            return db.execute("""SELECT 1 FROM address_history h JOIN addresses a
                ON h.wallet_id=a.wallet_id AND h.branch=a.branch AND h.idx=a.idx
                WHERE h.wallet_id=? AND a.address=? AND h.txid=? LIMIT 1""",
                (wid,address,txid)).fetchone() is not None
        for txid,parts in by_tx.items():
            affected={r['address'] for r in parts['inputs']+parts['outputs']}
            if affected and all(address_saw_tx(address,txid) for address in affected):
                db.execute('DELETE FROM local_broadcast_inputs WHERE wallet_id=? AND broadcast_txid=?',
                           (wid,txid))
                db.execute('DELETE FROM local_broadcast_outputs WHERE wallet_id=? AND broadcast_txid=?',
                           (wid,txid))
                continue
            for row in parts['inputs']:
                db.execute('DELETE FROM utxos WHERE wallet_id=? AND txid=? AND vout=?',
                           (wid,row['source_txid'],row['source_vout']))
            for row in parts['outputs']:
                # Another *accepted* local transaction may already have spent
                # this unconfirmed change before the server observed its parent.
                # Never resurrect it from the parent's own projection.
                if db.execute('''SELECT 1 FROM local_broadcast_inputs
                    WHERE wallet_id=? AND source_txid=? AND source_vout=?''',
                    (wid,txid,row['vout'])).fetchone():
                    continue
                # Once this address reports our transaction, its UTXO set is
                # authoritative: it might already have spent the new output.
                if not address_saw_tx(row['address'],txid):
                    db.execute("""INSERT OR IGNORE INTO utxos
                        (wallet_id,txid,vout,address,value,height,coinbase,tokens)
                        VALUES(?,?,?,?,?,0,0,0)""",
                        (wid,txid,row['vout'],row['address'],row['value']))

    def touch_connected(self, wid: str, tip_height: int, tip_hash: str):
        # Refresh liveness on a subscribed connection, never revive stale data.
        with self.db() as db:
            db.execute("UPDATE wallets SET last_sync=?,tip_height=?,tip_hash=? WHERE id=? AND scan_state='synced'",
                       (datetime.now(timezone.utc).isoformat(),tip_height,tip_hash,wid))

    def advance_tip(self, previous: tuple[int, str], new: tuple[int, str]):
        """Advance the cached height only for a contiguous, verified header extension.

        It is never an excuse to ignore scripthash change notifications. A
        disconnected or possibly reorganized header chain must trigger rescan.
        """
        old_height, old_hash = previous
        height, block_hash = new
        if height != old_height + 1:
            raise ValueError('El salto de altura no es consecutivo')
        with self.db() as db:
            db.execute('UPDATE wallets SET tip_height=?, tip_hash=? '
                       "WHERE scan_state='synced' AND tip_height=? AND tip_hash=?",
                       (height, block_hash, old_height, old_hash))

    def mark_error(self, wid: str, error: str):
        with self.db() as db:
            db.execute("UPDATE wallets SET scan_state='stale',error=? WHERE id=?",(error[:200],wid))
            db.commit()

    def issue_change(self,wid: str):
        wallet=self.get(wid)
        if wallet['wallet_type'].startswith('legacy-'):
            raise ValueError('Una wallet Legacy utiliza su dirección fija para el cambio')
        seed=self.seed(wid)
        with self.db() as db:
            row=db.execute('SELECT change_index FROM wallets WHERE id=?',(wid,)).fetchone()
            if row is None:raise ValueError('Billetera inexistente')
            idx=row['change_index']
            if idx>=100000:raise ValueError('Límite de direcciones de cambio')
            address=address_for(seed,self.network,1,idx,wallet['account_index'],wallet['derivation_coin_type'])
            from cashminer.wallet.crypto import script_hash
            # The HD scanner may already have stored this *unissued* lookahead address.
            # Mark the same derived address as issued; never reuse the index or overwrite
            # a mismatched row. Keep the issuance and next index in one transaction.
            sh=script_hash(address,self.network)
            inserted=db.execute('''INSERT INTO addresses(wallet_id,branch,idx,address,scripthash,issued)
                VALUES(?,?,?,?,?,1)
                ON CONFLICT(wallet_id,branch,idx) DO UPDATE SET issued=1
                WHERE addresses.address=excluded.address AND addresses.scripthash=excluded.scripthash''',
                (wid,1,idx,address,sh))
            if inserted.rowcount != 1:
                raise ValueError('Dirección de cambio HD incompatible con el índice guardado')
            db.execute('UPDATE wallets SET change_index=? WHERE id=?',(idx+1,wid))
            db.commit()
        return {'address':address,'branch':1,'idx':idx}

    def spending_utxos(self,wid: str):
        self.get(wid)
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT u.*,a.branch,a.idx FROM utxos u
                JOIN addresses a ON u.wallet_id=a.wallet_id AND u.address=a.address
                WHERE u.wallet_id=?''',(wid,))]

    def require_unspent_inputs(self,wid: str,input_refs):
        """Reject an old signed preview if another accepted spend used its inputs.

        This is a point-in-time validation, not a reservation. The Electrum
        server still decides whether a competing transaction is accepted.
        """
        refs=list(input_refs)
        if not refs:return  # Compatibility for empty-input diagnostic mocks.
        if len(set(tuple(ref) for ref in refs))!=len(refs):
            raise ValueError('La transacción preparada tiene entradas duplicadas')
        with self.db() as db:
            wallet=db.execute('SELECT scan_state FROM wallets WHERE id=?',(wid,)).fetchone()
            if not wallet or wallet['scan_state']!='synced':
                raise ValueError('La billetera necesita sincronizarse antes de transmitir')
            for txid,vout in refs:
                if not db.execute('SELECT 1 FROM utxos WHERE wallet_id=? AND txid=? AND vout=?',
                                  (wid,txid,vout)).fetchone():
                    raise ValueError('Los UTXO de esta vista previa cambiaron; prepará el envío nuevamente')

    def note_broadcast(self,wid: str,tx: dict):
        """Publish one *accepted* local transaction and its UTXO delta atomically.

        This does not reserve anything before broadcast. Local projections are
        replayed over lagging Electrum observations until the network reports
        the TXID in the history of all affected owned addresses.
        """
        ts=datetime.now(timezone.utc).isoformat()
        refs=list(tx.get('input_refs') or ())
        sources=list(tx.get('input_addresses') or ())
        if refs and len(refs)!=len(sources):
            raise ValueError('Faltan direcciones de origen para el gasto local')
        if len({tuple(r) for r in refs})!=len(refs):
            raise ValueError('La transacción contiene entradas repetidas')
        own_outputs=[(0,tx['destination'],tx['amount_sats'])]
        if tx.get('change_sats',0)>0:
            own_outputs.append((1,tx['change_address'],tx['change_sats']))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM wallets WHERE id=?',(wid,)).fetchone():
                raise ValueError('Billetera inexistente')
            for (source_txid,vout),address in zip(refs,sources):
                # Own inputs are known from the signed transaction, even when
                # a concurrent Electrum scan has already removed the row.
                if not db.execute('SELECT 1 FROM addresses WHERE wallet_id=? AND address=?',
                                  (wid,address)).fetchone():
                    raise ValueError('Entrada firmada no pertenece a la billetera')
                db.execute("""INSERT OR REPLACE INTO local_broadcast_inputs
                    (wallet_id,broadcast_txid,source_txid,source_vout,address)
                    VALUES(?,?,?,?,?)""",(wid,tx['txid'],source_txid,vout,address))
                db.execute('DELETE FROM utxos WHERE wallet_id=? AND txid=? AND vout=?',
                           (wid,source_txid,vout))
            for vout,address,value in own_outputs:
                if not db.execute('SELECT 1 FROM addresses WHERE wallet_id=? AND address=?',
                                  (wid,address)).fetchone():
                    continue
                db.execute("""INSERT OR REPLACE INTO local_broadcast_outputs
                    (wallet_id,broadcast_txid,vout,address,value) VALUES(?,?,?,?,?)""",
                    (wid,tx['txid'],vout,address,value))
                db.execute("""INSERT OR REPLACE INTO utxos
                    (wallet_id,txid,vout,address,value,height,coinbase,tokens)
                    VALUES(?,?,?,?,?,0,0,0)""",(wid,tx['txid'],vout,address,value))
            db.execute("""INSERT OR REPLACE INTO local_transactions
                (txid,wallet_id,created_at,raw_hex,state) VALUES(?,?,?,?,?)""",
                (tx['txid'],wid,ts,'','broadcast'))
            owners=db.execute('SELECT wallet_id FROM addresses WHERE address=?',
                              (tx['destination'],)).fetchall()
            db.commit()
        return [r['wallet_id'] for r in owners]

    def utxos(self,wid: str):
        self.get(wid)
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM utxos WHERE wallet_id=?',(wid,))]

    def history(self,wid: str):
        self.get(wid)
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM history WHERE wallet_id=? ORDER BY height DESC',(wid,))]

    def servers(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM servers WHERE enabled=1 ORDER BY host,port')]

    def add_server(self,host: str,port: int,cert_sha256: str | None = None):
        import ipaddress
        import re
        host=host.strip().lower()
        if not re.fullmatch(r'[a-z0-9.-]{1,253}',host) or host.startswith(('.', '-')) or '..' in host:
            raise ValueError('Nombre de servidor no válido')
        if not isinstance(port,int) or not 1<=port<=65535:
            raise ValueError('Puerto inválido')
        # Pinning opcional únicamente con autorización explícita del usuario.
        if cert_sha256 is not None:
            import re
            cert_sha256 = str(cert_sha256).replace(':','').strip().lower()
            if not re.fullmatch(r'[0-9a-f]{64}', cert_sha256):
                raise ValueError('Huella TLS SHA-256 inválida: deben ser 64 caracteres hexadecimales')
        if self.network == 'testnet3':
            from cashminer.wallet.electrum import TESTNET3_BAD_LEGACY, TESTNET3_ALTERNATE
            if (host,port) in TESTNET3_BAD_LEGACY:
                raise ValueError('Puerto de Mainnet incorrecto para Testnet3')
            if (host,port) == TESTNET3_ALTERNATE and not cert_sha256:
                raise ValueError('Ese servidor autofirmado requiere una huella TLS SHA-256 verificada y aprobada')
        with self.db() as db:
            # No sobrescribe wallets ni otras configuraciones del usuario.
            db.execute('INSERT OR REPLACE INTO servers(host,port,enabled,tls_cert_sha256) VALUES(?,?,1,?)',
                       (host,port,cert_sha256))
            db.commit()
        return {'host':host,'port':port,'pinned':bool(cert_sha256)}

    def save_local_tx(self,wid: str,txid: str,raw: str,state: str):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO local_transactions(txid,wallet_id,created_at,raw_hex,state) VALUES(?,?,?,?,?)',
                       (txid,wid,datetime.now(timezone.utc).isoformat(),raw,state))
            db.commit()
