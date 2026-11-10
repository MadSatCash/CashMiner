"""Wallet mínima de minería para *tempnet* (solo recepción por coinbase).

No incluye seguimiento de UTXO ni funciones para gastar monedas. No reutiliza
claves de mainnet, ni importa claves de otras billeteras.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Optional

FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GENERATOR = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
CHARS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
PREFIX = "bchtest"


def _add_points(a, b):
    if a is None:
        return b
    if b is None:
        return a
    x1, y1 = a
    x2, y2 = b
    if x1 == x2 and (y1 + y2) % FIELD == 0:
        return None
    if a == b:
        slope = ((3 * x1 * x1) * pow(2 * y1, -1, FIELD)) % FIELD
    else:
        slope = ((y2 - y1) * pow(x2 - x1, -1, FIELD)) % FIELD
    x3 = (slope * slope - x1 - x2) % FIELD
    y3 = (slope * (x1 - x3) - y1) % FIELD
    return x3, y3


def compressed_pubkey(secret: int) -> bytes:
    if not (1 <= secret < ORDER):
        raise ValueError("clave privada fuera del rango secp256k1")
    result = None
    base = GENERATOR
    scalar = secret
    while scalar:
        if scalar & 1:
            result = _add_points(result, base)
        base = _add_points(base, base)
        scalar >>= 1
    if result is None:
        raise ValueError("clave privada inválida")
    x, y = result
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def _convertbits(data, source: int, dest: int, pad: bool = True):
    acc = bits = 0
    output = []
    for value in data:
        if value < 0 or value >> source:
            raise ValueError("valor inválido para convertbits")
        acc = (acc << source) | value
        bits += source
        while bits >= dest:
            bits -= dest
            output.append((acc >> bits) & ((1 << dest) - 1))
    if pad and bits:
        output.append((acc << (dest - bits)) & ((1 << dest) - 1))
    elif not pad and (bits >= source or ((acc << (dest - bits)) & ((1 << dest) - 1))):
        raise ValueError("padding inválido")
    return output


def _polymod(values):
    crc = 1
    generators = (0x98F2BC8E61, 0x79B76D99E2, 0xF33E5FB3C4, 0xAE2EABE2A8, 0x1E4F43E470)
    for value in values:
        upper = crc >> 35
        crc = ((crc & 0x07FFFFFFFF) << 5) ^ value
        for i, generator in enumerate(generators):
            if (upper >> i) & 1:
                crc ^= generator
    return crc ^ 1


def pubkey_to_cashaddr(public_key: bytes) -> str:
    sha = hashlib.sha256(public_key).digest()
    try:
        h160 = hashlib.new("ripemd160", sha).digest()
    except ValueError as e:
        raise RuntimeError("Tu Python/OpenSSL no tiene RIPEMD160; no puedo generar una dirección") from e
    # version byte 0 = P2PKH, hash de 20 bytes.
    data = _convertbits(b"\x00" + h160, 8, 5)
    checksum_inputs = [ord(ch) & 31 for ch in PREFIX] + [0] + data + [0] * 8
    checksum = _polymod(checksum_inputs)
    check = [(checksum >> (5 * (7 - i))) & 31 for i in range(8)]
    return PREFIX + ":" + "".join(CHARS[i] for i in data + check)


def address_for_private_key(secret: int) -> str:
    return pubkey_to_cashaddr(compressed_pubkey(secret))


def load_wallet(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("network") != "tempnet" or data.get("format") != "cashminer-tempnet-wallet-v1":
        raise ValueError("Archivo de wallet incompatible")
    secret = int(data["private_key_hex"], 16)
    if address_for_private_key(secret) != data.get("address"):
        raise ValueError("El par de claves y la dirección no coinciden")
    return data


def load_or_create_wallet(path: str | os.PathLike, *, create: bool = True) -> dict:
    path = Path(path)
    if path.exists():
        return load_wallet(path)
    if not create:
        raise FileNotFoundError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.randbelow(ORDER - 1) + 1
    data = {
        "format": "cashminer-tempnet-wallet-v1",
        "network": "tempnet",
        "address": address_for_private_key(secret),
        "public_key_hex": compressed_pubkey(secret).hex(),
        "private_key_hex": f"{secret:064x}",
        "warning": "TESTNET SOLAMENTE. No importar estas claves en mainnet.",
    }
    # Escritura exclusiva: no sobrescribimos jamás una wallet existente.
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if os.name == "posix":
        os.chmod(path, 0o600)
    return data
