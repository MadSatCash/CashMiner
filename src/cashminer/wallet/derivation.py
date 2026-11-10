"""BIP44 account-level paths for wallet-only HD derivation.

Account path is m/44'/coin_type'/account'. Each address appends /branch/index.
Only P2PKH BIP44 is supported. Do not conflate derivation with network identity.
"""
from __future__ import annotations
import re
from cashminer.wallet.crypto import COIN_TYPE

# New-wallet presets only. The persisted coin_type always controls an existing wallet.
# BCH BIP44 coin type 145 matches Electron Cash on both BCH mainnet and testnets.
DEFAULT_COIN_TYPE = {'mainnet':145, 'testnet3':145, 'testnet4':145, 'chipnet':145,
                     'tempnet_fablous_2026':1, 'regtest':1}
PATH_PATTERN = re.compile(r"m/44'/([0-9]+)'/([0-9]+)'\Z")


def account_path(coin_type: int, account: int) -> str:
    if type(coin_type) is not int or not 0 <= coin_type < 0x80000000:
        raise ValueError('El tipo de moneda BIP44 debe estar entre 0 y 2147483647')
    if type(account) is not int or not 0 <= account <= 1000:
        raise ValueError('La cuenta BIP44 debe estar entre 0 y 1000')
    return f"m/44'/{coin_type}'/{account}'"


def parse_account_path(value: str) -> tuple[int, int]:
    if not isinstance(value,str) or len(value)>64:
        raise ValueError('Ruta de derivación inválida')
    match=PATH_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("Usá una ruta de cuenta BIP44 completa, por ejemplo m/44'/145'/0'")
    coin_type,account=map(int,match.groups())
    account_path(coin_type,account)  # enforce range and canonical form
    return coin_type,account


def default_account_path(network: str) -> str:
    if network not in COIN_TYPE:
        raise ValueError('Red de billeteras desconocida')
    return account_path(DEFAULT_COIN_TYPE[network],0)


def historical_account_path(network: str,account: int=0) -> str:
    # Exact v2.3.3 route, for existing vaults without a derivation field.
    return account_path(COIN_TYPE[network],account)
