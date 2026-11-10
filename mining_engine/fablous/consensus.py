"""Consenso FABLOUS de minería para tempnet 2026.

Implementación independiente desde CHIP-2025-03; NO es un nodo completo.
Solo calcula ticks, subsidios, ASERT y comprueba cabeceras PoW.

Referencia normativa: https://gitlab.com/0353F40E/fablous/-/raw/master/readme.md
"""
from __future__ import annotations

import hashlib
import struct

# Tempnet 2026 se separa en el primer bloque post-activación, 327989.
# El último bloque de 600 ticks es el 327988.
ACTIVATION_HEIGHT = 327988
FIRST_POST_ACTIVATION_HEIGHT = ACTIVATION_HEIGHT + 1
COMMON_HASH = "00000000000002bcc82b979f71d827d7788c84b981975101cb9e415ace23c46c"
FIRST_HASH = "00000000e18af2c66d44a1bbfe165acc4b87a625d211a09e33d5ee61d35dcb66"
PEERS = ("15.204.253.47:48335", "15.204.228.134:48333", "135.148.26.244:48333")
P2P_MAGIC = bytes.fromhex("e2b7daaf")
P2P_PORT = 48333
CASHADDR_PREFIX = "bchtest"

# Chipnet comparte la historia de testnet4 hasta su bifurcación original,
# incluida el ancla ASERT de noviembre de 2020.
ASERT_ANCHOR_HEIGHT = 16844
ASERT_ANCHOR_BITS = 0x1D00FFFF
ASERT_ANCHOR_PARENT_TIME = 1605451779
ASERT_ANCHOR_INTERVAL = 600
ASERT_HALFLIFE = 3600
RADIX = 1 << 16
POW_LIMIT_BITS = 0x1D00FFFF


def ticks_at_height(height: int) -> int:
    if height < 0:
        raise ValueError("height negativo")
    if height <= ACTIVATION_HEIGHT:
        return height * 600
    return ACTIVATION_HEIGHT * 600 + (height - ACTIVATION_HEIGHT) * 60


def interval_for_height(height: int) -> int:
    if height < 0:
        raise ValueError("height negativo")
    return 60 if height > ACTIVATION_HEIGHT else 600


def block_subsidy_sats(height: int) -> int:
    if height < 0:
        raise ValueError("height negativo")
    tick = ticks_at_height(height)
    chunk = (tick + 599) // 600
    halvings = chunk // 210000
    if halvings >= 64:
        return 0
    return ((50 * 100_000_000) >> halvings) * interval_for_height(height) // 600


def bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if not mantissa or bits & 0x00800000 or exponent <= 0:
        raise ValueError(f"nBits inválido: {bits:08x}")
    target = mantissa >> (8 * (3 - exponent)) if exponent <= 3 else mantissa << (8 * (exponent - 3))
    if not (0 < target <= (1 << 256) - 1):
        raise ValueError("target fuera del rango de 256 bits")
    return target


def target_to_bits(target: int) -> int:
    if target <= 0:
        raise ValueError("target <= 0")
    size = (target.bit_length() + 7) // 8
    mantissa = target << (8 * (3 - size)) if size <= 3 else target >> (8 * (size - 3))
    if mantissa & 0x00800000:
        mantissa >>= 8
        size += 1
    return (size << 24) | (mantissa & 0x007FFFFF)


def _trunc_div(n: int, d: int) -> int:
    return (abs(n) // abs(d)) * (-1 if (n < 0) != (d < 0) else 1)


def expected_bits(parent_height: int, parent_time: int, candidate_time: int) -> int:
    """Bits de bloque H = parent_height+1, usando H-1 como ASERT eval."""
    next_interval = interval_for_height(parent_height + 1)
    if candidate_time - parent_time > 2 * next_interval:
        return POW_LIMIT_BITS

    time_delta = parent_time - ASERT_ANCHOR_PARENT_TIME
    tick_delta = ticks_at_height(parent_height) - ticks_at_height(ASERT_ANCHOR_HEIGHT)
    exponent = _trunc_div(
        (time_delta - (tick_delta + ASERT_ANCHOR_INTERVAL)) * RADIX,
        ASERT_HALFLIFE,
    )
    num_shifts = exponent >> 16
    fraction = exponent - num_shifts * RADIX
    factor = ((195766423245049 * fraction + 971821376 * fraction**2
               + 5127 * fraction**3 + (1 << 47)) >> 48) + RADIX
    target = bits_to_target(ASERT_ANCHOR_BITS) * factor
    if num_shifts < 0:
        target >>= -num_shifts
    else:
        target <<= num_shifts
    target >>= 16
    target *= ASERT_ANCHOR_INTERVAL // next_interval
    target = max(1, min(bits_to_target(POW_LIMIT_BITS), target))
    return target_to_bits(target)


def parse_header(header: bytes) -> dict:
    if len(header) != 80:
        raise ValueError("header debe tener 80 bytes")
    digest = hashlib.sha256(hashlib.sha256(header).digest()).digest()
    return {
        "version": struct.unpack_from("<I", header, 0)[0],
        "hash": digest[::-1].hex(),
        "hash_le": digest,
        "prev_hash": header[4:36][::-1].hex(),
        "time": struct.unpack_from("<I", header, 68)[0],
        "bits": struct.unpack_from("<I", header, 72)[0],
        "nonce": struct.unpack_from("<I", header, 76)[0],
    }


def validate_header(header: bytes, *, parent_height: int, parent_hash: str,
                    parent_time: int, enforce_diff: bool = True) -> dict:
    info = parse_header(header)
    if info["prev_hash"] != parent_hash:
        raise ValueError("cabecera no conecta con su padre")
    target = bits_to_target(info["bits"])
    if target > bits_to_target(POW_LIMIT_BITS):
        raise ValueError("target supera powLimit")
    if int.from_bytes(info["hash_le"], "little") > target:
        raise ValueError("la cabecera no satisface Proof of Work")
    if enforce_diff:
        bits_expected = expected_bits(parent_height, parent_time, info["time"])
        if info["bits"] != bits_expected:
            raise ValueError(f"nBits distinto del calculado: recibido={info['bits']:08x}, esperado={bits_expected:08x}")
    return info


def block_work(bits: int) -> int:
    target = bits_to_target(bits)
    return (1 << 256) // (target + 1)
