"""BCH wallet-only cryptographic primitives. No miner state or Node.js dependency.

The recoverable root is raw BIP32 seed material (32 CSPRNG bytes), NOT a BIP39 mnemonic.
Secrets are protected by Windows DPAPI and can only be recovered on a different
computer using an explicitly exported 64-character recovery seed.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import os
import secrets
import sys
from dataclasses import dataclass
ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

HARDENED = 0x80000000
COIN_TYPE = {'mainnet': 145, 'testnet3': 1, 'testnet4': 1, 'chipnet': 1,
             'tempnet_fablous_2026': 1, 'regtest': 1}
PREFIX = {'mainnet': 'bitcoincash', 'testnet3': 'bchtest', 'testnet4': 'bchtest',
          'chipnet': 'bchtest',
          'tempnet_fablous_2026': 'bchtest', 'regtest': 'bchreg'}


def sha256d(blob: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(blob).digest()).digest()


def hash160(blob: bytes) -> bytes:
    return hashlib.new('ripemd160', hashlib.sha256(blob).digest()).digest()


def public_key(scalar: int, compressed: bool = True) -> bytes:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    if not 0 < scalar < ORDER:
        raise ValueError('Clave secp256k1 inválida')
    return ec.derive_private_key(scalar, ec.SECP256K1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.CompressedPoint if compressed else PublicFormat.UncompressedPoint)


def derive_private(seed: bytes, network: str, branch: int, index: int, account: int = 0, coin_type: int | None = None) -> int:
    if network not in COIN_TYPE or branch not in (0, 1) or not 0 <= index < HARDENED or not 0 <= account < HARDENED:
        raise ValueError('Ruta HD inválida')
    if coin_type is None: coin_type = COIN_TYPE[network]
    if type(coin_type) is not int or not 0 <= coin_type < HARDENED:
        raise ValueError('Tipo de moneda BIP44 inválido')
    if not 16 <= len(seed) <= 64:
        raise ValueError('Longitud de semilla BIP32 inválida')
    digest = hmac.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
    k, chain = int.from_bytes(digest[:32], 'big'), digest[32:]
    if not 0 < k < ORDER:
        raise ValueError('Raíz BIP32 inválida')
    for step in (44 | HARDENED, coin_type | HARDENED,
                 account | HARDENED, branch, index):
        data = (b'\x00' + k.to_bytes(32, 'big') if step & HARDENED else public_key(k))
        digest = hmac.new(chain, data + step.to_bytes(4, 'big'), hashlib.sha512).digest()
        offset = int.from_bytes(digest[:32], 'big')
        if offset >= ORDER:
            raise ValueError('Derivación BIP32 inválida')
        k = (k + offset) % ORDER
        if not k:
            raise ValueError('Clave derivada nula')
        chain = digest[32:]
    return k


def convertbits(data, frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = bits = 0
    out = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or value >> frombits:
            raise ValueError('Símbolo CashAddr inválido')
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits: out.append((acc << (tobits-bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits-bits)) & maxv):
        raise ValueError('Padding CashAddr inválido')
    return out


def polymod(values: list[int]) -> int:
    c = 1
    for v in values:
        top = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ v
        for i,g in enumerate((0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4,
                              0xae2eabe2a8, 0x1e4f43e470)):
            if (top >> i) & 1: c ^= g
    return c ^ 1


def encode_address(pkh: bytes, network: str) -> str:
    if len(pkh) != 20: raise ValueError('Sólo P2PKH de 20 bytes')
    prefix = PREFIX[network]
    d = convertbits(b'\x00' + pkh, 8, 5, True)
    crc = polymod([ord(c)&31 for c in prefix] + [0] + d + [0]*8)
    return prefix + ':' + ''.join(ALPHABET[v] for v in d + [((crc >> (5*(7-i))) & 31) for i in range(8)])


def decode_cashaddr(address: str, network: str):
    """Decode BCH CashAddr and return (type, 20-byte hash).

    Destination types 0=P2PKH, 1=P2SH. Tokens do not use a distinct
    destination locking script; token-aware CashAddr types 2, 3 are not
    supported for safe experimental spending.
    """
    if not isinstance(address, str) or address != address.lower():
        raise ValueError('CashAddr debe estar en minúsculas y tener prefijo')
    prefix,sep,tail = address.partition(':')
    if not sep or prefix != PREFIX[network] or len(tail) < 8 or any(c not in ALPHABET for c in tail):
        raise ValueError('Dirección CashAddr para otra red o con caracteres inválidos')
    d = [ALPHABET.index(c) for c in tail]
    if polymod([ord(c)&31 for c in prefix] + [0] + d) != 0:
        raise ValueError('Checksum CashAddr incorrecto')
    result = bytes(convertbits(d[:-8], 5, 8, False))
    if len(result) != 21 or result[0] not in (0,8):
        raise ValueError('Por seguridad sólo se admiten destinos P2PKH/P2SH de 20 bytes')
    return result[0]>>3,result[1:]


def decode_address(address: str, network: str) -> bytes:
    addr_type,payload=decode_cashaddr(address,network)
    if addr_type!=0:
        raise ValueError('La dirección no es P2PKH')
    return payload


def destination_script(address: str, network: str) -> bytes:
    kind,payload=decode_cashaddr(address,network)
    return p2pkh_script(payload) if kind==0 else b'\xa9\x14'+payload+b'\x87'


def address_for(seed: bytes, network: str, branch: int, index: int, account: int = 0, coin_type: int | None = None) -> str:
    return encode_address(hash160(public_key(derive_private(seed, network, branch, index, account, coin_type))), network)


def address_for_legacy(scalar: int, network: str, compressed: bool = True) -> str:
    return encode_address(hash160(public_key(scalar, compressed=compressed)), network)


def p2pkh_script(pkh: bytes) -> bytes:
    if len(pkh) != 20: raise ValueError('P2PKH inválido')
    return bytes.fromhex('76a914') + pkh + bytes.fromhex('88ac')


def script_hash(address: str, network: str) -> str:
    return hashlib.sha256(p2pkh_script(decode_address(address, network))).digest()[::-1].hex()


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(buf: bytes):
    # The caller holds the source buffer alive until the DPAPI call completes.
    backing = ctypes.create_string_buffer(buf, len(buf))
    return _DATA_BLOB(len(buf), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte))), backing


def _dpapi(data: bytes, entropy: bytes, decrypt: bool) -> bytes:
    if sys.platform != 'win32':
        raise RuntimeError('Protección automática sin contraseña disponible solamente en Windows (DPAPI).')
    from ctypes import windll
    crypt32 = windll.crypt32
    kernel32 = windll.kernel32
    ptr = ctypes.POINTER(_DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [ptr, ctypes.c_wchar_p, ptr, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.DWORD, ptr]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [ptr, ctypes.c_void_p, ptr, ctypes.c_void_p,
                                           ctypes.c_void_p, wintypes.DWORD, ptr]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source, source_buffer = _blob(data)
    extra, extra_buffer = _blob(entropy)
    result = _DATA_BLOB()
    # UI forbidden; never ask for password. Memory returned by Windows is released.
    flag = 0x1
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(extra),
                                       None, None, flag, ctypes.byref(result))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(source), 'CashMiner Wallet v2.3',
                                     ctypes.byref(extra), None, None, flag, ctypes.byref(result))
    if not ok:
        raise OSError('Windows DPAPI no pudo proteger/abrir la semilla de esta billetera')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def protect_seed(seed: bytes, wallet_id: str) -> bytes:
    return _dpapi(seed, b'CashMiner-v2.3-wallet:' + wallet_id.encode('ascii'), False)


def unprotect_seed(ciphertext: bytes, wallet_id: str) -> bytes:
    seed = _dpapi(ciphertext, b'CashMiner-v2.3-wallet:' + wallet_id.encode('ascii'), True)
    if not 16 <= len(seed) <= 64:
        raise ValueError('El material recuperado tiene longitud inesperada')
    return seed


def new_seed() -> bytes:
    return secrets.token_bytes(32)  # CSPRNG del SO, 256 bits de entropía
