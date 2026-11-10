"""Migración explícita, verificable y no destructiva de CashMiner2 a CashMiner.

No se invoca desde el arranque: evita copiar secretos o SQLite mientras otras
versiones permanecen abiertas. El origen NUNCA se borra.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from cashminer.config import canonical_data_home, legacy_data_home


def _check_no_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeError('No se admiten enlaces simbólicos en el directorio de datos')
    for current, folders, files in os.walk(root, followlinks=False):
        for entry in folders + files:
            if (Path(current)/entry).is_symlink():
                raise RuntimeError('Hay enlaces simbólicos en los datos; revisar antes de migrar')


def _hash(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def _copy_verified(src: Path, dst: Path) -> None:
    if dst.exists():
        if src.is_file() and _hash(src)==_hash(dst):
            return
        raise RuntimeError('Conflicto de archivos al migrar: '+str(dst))
    dst.parent.mkdir(parents=True,exist_ok=True)
    if src.suffix.lower() in ('.sqlite','.sqlite3','.db'):
        uri='file:'+quote(str(src.resolve()),safe='/:')+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as current:
            with closing(sqlite3.connect(dst)) as target:
                current.backup(target)
                target.commit()
                check=target.execute('PRAGMA quick_check').fetchone()
                if check is None or check[0] != 'ok':
                    raise RuntimeError('SQLite no pasó quick_check: '+str(src))
        return
    # No conservar WAL/SHM sueltos: cada SQLite se copia mediante backup.
    if src.suffix.lower() in ('.sqlite-wal','.sqlite-shm','.db-wal','.db-shm'):
        return
    shutil.copy2(src,dst)
    if _hash(src)!=_hash(dst):
        raise RuntimeError('Error de integridad copiando '+str(src))


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():return
    for path in sorted(src.rglob('*')):
        relative=path.relative_to(src)
        out=dst/relative
        if path.is_dir():out.mkdir(parents=True,exist_ok=True)
        elif path.is_file() and not path.name.endswith(('-wal','-shm')):
            _copy_verified(path,out)


def migrate_paths(source: Path | None = None, destination: Path | None = None,
                  *, apply: bool = False) -> dict:
    """Dry-run by default. Publish atomically only after every check succeeds.

    Caller must close all CashMiner versions first. Leaves source fully intact.
    Never uses the runtime directory as a source for executable Python or DLLs.
    """
    old=Path(source) if source is not None else legacy_data_home()
    new=Path(destination) if destination is not None else canonical_data_home()
    if not old.is_dir(): raise FileNotFoundError('No existe la instalación anterior: '+str(old))
    if new.exists(): raise FileExistsError('La carpeta de destino ya existe: '+str(new))
    if old.resolve()==new.resolve(): raise ValueError('Origen y destino coinciden')
    if new.resolve().is_relative_to(old.resolve()) or old.resolve().is_relative_to(new.resolve()):
        raise ValueError('Origen y destino no deben estar anidados')
    _check_no_symlinks(old)
    mappings=[
        ('settings.json','settings.json'),
        ('wallet_v23','wallets'),
        ('wallets','wallets/legacy'),
        ('networks','networks'),
        ('logs','logs'),
        ('runtime/tempnet_v6_2/logs','mining/logs'),
        ('runtime/tempnet_v6_2/found_blocks','mining/found_blocks'),
        ('runtime/tempnet_v6_2/tempnet_wallet.json','wallets/legacy/tempnet_wallet.json'),
        # If someone ran v2.8 against the legacy data root before migration,
        # include new-style mining artifacts generated during that period.
        ('mining','mining'),
    ]
    available=[(str(old/a),str(new/b)) for a,b in mappings if (old/a).exists()]
    report={'source':str(old),'destination':str(new),'items':available,'applied':False,
            'original_preserved':True}
    if not apply:return report
    new.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.cashminer-migrate-',dir=new.parent))
    try:
        for left,right in mappings:
            src=old/left;dst=stage/right
            if src.is_dir():_copy_tree(src,dst)
            elif src.is_file():_copy_verified(src,dst)
        # Check the copied databases again, independently of the copy operation.
        for db in stage.rglob('*'):
            if db.is_file() and db.suffix.lower() in ('.sqlite','.sqlite3','.db'):
                with closing(sqlite3.connect('file:'+quote(str(db.resolve()),safe='/:')+'?mode=ro',uri=True)) as conn:
                    if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                        raise RuntimeError('SQLite migrado inválido: '+str(db))
        os.replace(stage,new)
        report['applied']=True
        return report
    except Exception:
        shutil.rmtree(stage,ignore_errors=True)
        raise
