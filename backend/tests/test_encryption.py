import pytest
from cryptography.exceptions import InvalidTag

from app.core.encryption import decrypt, encrypt


def test_roundtrip():
    secret = b"plaid-access-token-123"
    assert decrypt(encrypt(secret)) == secret


def test_ciphertext_differs_each_call():
    a, b = encrypt(b"same"), encrypt(b"same")
    assert a != b  # random DEK + nonce
    assert decrypt(a) == decrypt(b) == b"same"


def test_tamper_detected():
    blob = bytearray(encrypt(b"x"))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        decrypt(bytes(blob))


def test_aad_context_binding():
    secret = b"plaid-access-token-123"
    blob = encrypt(secret, aad=b"ctxA")
    with pytest.raises(InvalidTag):
        decrypt(blob, aad=b"ctxB")
    assert decrypt(blob, aad=b"ctxA") == secret
