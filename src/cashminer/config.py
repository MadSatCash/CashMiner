"""Ubicaciones de datos de CashMiner, independientes de la versión del producto.

Una instalación existente de CashMiner2 se sigue leyendo EN SU LUGAR hasta
que el usuario ejecute el migrador con la aplicación y los mineros cerrados.
Nunca movemos billeteras ni copiamos secretos silenciosamente al arrancar.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _platform_base() -> Path:
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData'/'Local')))
    if sys.platform == 'darwin':
        return Path.home()/'Library'/'Application Support'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local'/'share')))


def canonical_data_home() -> Path:
    return _platform_base()/('cashminer' if sys.platform not in ('win32','darwin') else 'CashMiner')


def legacy_data_home() -> Path:
    return _platform_base()/('cashminer2' if sys.platform not in ('win32','darwin') else 'CashMiner2')


def data_home() -> Path:
    custom = os.environ.get('CASHMINER_DATA_DIR') or os.environ.get('CASHMINER2_DATA_DIR')
    if custom:
        return Path(custom).expanduser().resolve()
    modern=canonical_data_home()
    legacy=legacy_data_home()
    # Existing users keep their real wallets when launching v2.8 for the first
    # time. A separate, explicit migration establishes the modern root.
    if not modern.exists() and legacy.exists():
        return legacy
    return modern


def is_legacy_layout(root: Path | None = None) -> bool:
    home = Path(root) if root is not None else data_home()
    return ((home/'wallet_v23').exists() or
            (home == legacy_data_home() and not (home/'wallets'/'mainnet').exists()))


def modern_wallets_home() -> Path:
    home=data_home()
    return home/('wallet_v23' if is_legacy_layout(home) else 'wallets')


def legacy_wallets_home() -> Path:
    home=data_home()
    return home/'wallets' if is_legacy_layout(home) else home/'wallets'/'legacy'


def mining_logs_home() -> Path:
    home=data_home()
    return home/'runtime'/'tempnet_v6_2'/'logs' if is_legacy_layout(home) else home/'mining'/'logs'


def found_blocks_home() -> Path:
    home=data_home()
    return home/'runtime'/'tempnet_v6_2'/'found_blocks' if is_legacy_layout(home) else home/'mining'/'found_blocks'


def legacy_miner_wallet_path() -> Path:
    home=data_home()
    return (home/'runtime'/'tempnet_v6_2'/'tempnet_wallet.json' if is_legacy_layout(home)
            else home/'wallets'/'legacy'/'tempnet_wallet.json')


def network_db_path(network: str, root: Path | None = None) -> Path:
    return (root or data_home())/'networks'/(network+'.sqlite')
