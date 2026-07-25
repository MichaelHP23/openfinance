import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_KEK = hashlib.sha256(settings.app_secret_key.encode()).digest()  # 32-byte KEK


def _seal(key: bytes, data: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def _open(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, aad)


def encrypt(plaintext: bytes, aad: bytes = b"") -> bytes:
    dek = os.urandom(32)
    wrapped = _seal(_KEK, dek)  # 12 + 32 + 16 = 60 bytes
    return len(wrapped).to_bytes(2, "big") + wrapped + _seal(dek, plaintext, aad)


def decrypt(blob: bytes, aad: bytes = b"") -> bytes:
    wlen = int.from_bytes(blob[:2], "big")
    wrapped, body = blob[2 : 2 + wlen], blob[2 + wlen :]
    dek = _open(_KEK, wrapped)
    return _open(dek, body, aad)
