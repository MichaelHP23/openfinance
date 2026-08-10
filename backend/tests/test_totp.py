from app.services.totp import (
    _hotp,  # internal, exercised directly against RFC test vectors
    generate_secret,
    provisioning_uri,
    verify_totp,
)


def test_generate_secret_is_base32_and_random():
    a, b = generate_secret(), generate_secret()
    assert a != b
    assert len(a) == 32  # base32(20 random bytes)


def test_provisioning_uri_shape():
    uri = provisioning_uri("JBSWY3DPEHPK3PXP", "a@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "a@example.com" in uri


def test_hotp_matches_rfc4226_test_vectors():
    # RFC 4226 Appendix D — secret "12345678901234567890" (ASCII), counters 0-2.
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    assert _hotp(secret, 0) == "755224"
    assert _hotp(secret, 1) == "287082"
    assert _hotp(secret, 2) == "359152"


def test_verify_totp_accepts_current_code_and_rejects_wrong_one():
    secret = generate_secret()
    now = 1_700_000_000
    code = _hotp(secret, now // 30)
    assert verify_totp(secret, code, at=now) is True
    assert verify_totp(secret, "000000", at=now) is False


def test_verify_totp_tolerates_one_step_of_clock_drift():
    secret = generate_secret()
    now = 1_700_000_000
    previous_step_code = _hotp(secret, (now // 30) - 1)
    assert verify_totp(secret, previous_step_code, at=now) is True
    two_steps_back = _hotp(secret, (now // 30) - 2)
    assert verify_totp(secret, two_steps_back, at=now) is False
