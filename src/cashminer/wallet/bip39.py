"""BIP39 English mnemonic conversion, checksum and seed derivation.

Uses the 2048-word BIP39 wordlist, hashlib PBKDF2-HMAC-SHA512 (2048 rounds),
NFKD and an operating-system cryptographic RNG. No extra runtime dependency.
The wallet currently uses an empty BIP39 passphrase unless one is explicitly
provided to :func:`mnemonic_to_seed`; the GUI never asks for a password.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import secrets
import unicodedata


def _nfkd(s: str) -> str:
    return unicodedata.normalize('NFKD', s)


@lru_cache(maxsize=1)
def _words() -> tuple[str, ...]:
    words = tuple(Path(__file__).with_name('bip39_english.txt').read_text('utf-8').splitlines())
    if len(words) != 2048 or len(set(words)) != 2048 or words[0] != 'abandon' or words[-1] != 'zoo':
        raise RuntimeError('La lista de palabras BIP39 está incompleta o alterada')
    return words


def entropy_to_mnemonic(entropy: bytes) -> str:
    if not isinstance(entropy, bytes) or len(entropy) not in (16, 20, 24, 28, 32):
        raise ValueError('BIP39 requiere 128, 160, 192, 224 o 256 bits de entropía')
    cs_len = len(entropy) * 8 // 32
    bits = ''.join(f'{b:08b}' for b in entropy)
    bits += ''.join(f'{b:08b}' for b in hashlib.sha256(entropy).digest())[:cs_len]
    words = _words()
    return ' '.join(words[int(bits[i:i + 11], 2)] for i in range(0, len(bits), 11))


def mnemonic_to_entropy(mnemonic: str) -> bytes:
    if not isinstance(mnemonic, str):
        raise ValueError('Frase de recuperación inválida')
    provided = _nfkd(mnemonic).strip().lower().split()
    if len(provided) not in (12, 15, 18, 21, 24):
        raise ValueError('La frase BIP39 requiere 12, 15, 18, 21 o 24 palabras')
    lookup = {word: index for index, word in enumerate(_words())}
    try:
        bits = ''.join(f'{lookup[word]:011b}' for word in provided)
    except KeyError as exc:
        raise ValueError('La frase contiene una palabra fuera de la lista BIP39 en inglés') from exc
    entropy_bits = len(bits) * 32 // 33
    entropy = int(bits[:entropy_bits], 2).to_bytes(entropy_bits // 8, 'big')
    checksum = ''.join(f'{b:08b}' for b in hashlib.sha256(entropy).digest())[:len(bits) - entropy_bits]
    if bits[entropy_bits:] != checksum:
        raise ValueError('El checksum BIP39 no coincide: revisá las palabras y su orden')
    return entropy


def mnemonic_to_seed(mnemonic: str, passphrase: str = '') -> bytes:
    # Validate checksum before deriving; do not accept words that only look right.
    entropy = mnemonic_to_entropy(mnemonic)
    normalized_phrase = entropy_to_mnemonic(entropy)
    return hashlib.pbkdf2_hmac('sha512', _nfkd(normalized_phrase).encode('utf-8'),
                               _nfkd('mnemonic' + passphrase).encode('utf-8'), 2048, dklen=64)


def new_mnemonic() -> str:
    return entropy_to_mnemonic(secrets.token_bytes(32))  # 256 bits of real entropy
