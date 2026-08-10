import time

import pytest

from app.services import auth, twofa
from app.services.totp import _hotp


def test_enrollment_round_trip(db):
    user = auth.register(db, "2fa@example.com", "pw12345")
    secret, uri = twofa.start_enrollment(db, user)
    assert uri.startswith("otpauth://totp/")
    assert user.totp_enabled is False  # not enabled until confirmed

    code = _hotp(secret, int(time.time()) // 30)
    assert twofa.confirm_enrollment(db, user, code) is True
    assert user.totp_enabled is True


def test_confirm_enrollment_wrong_code_does_not_enable(db):
    user = auth.register(db, "2fawrong@example.com", "pw12345")
    twofa.start_enrollment(db, user)
    assert twofa.confirm_enrollment(db, user, "000000") is False
    assert user.totp_enabled is False


def test_totp_secret_is_encrypted_at_rest(db):
    user = auth.register(db, "2faenc@example.com", "pw12345")
    secret, _ = twofa.start_enrollment(db, user)
    assert secret.encode() not in user.totp_secret  # never stored in the clear


def test_verify_login_code_requires_enabled(db):
    user = auth.register(db, "2fadisabled@example.com", "pw12345")
    secret, _ = twofa.start_enrollment(db, user)
    code = _hotp(secret, int(time.time()) // 30)
    # confirmed enrollment but the flow hasn't called confirm_enrollment yet
    assert twofa.verify_login_code(db, user, code) is False


def test_preauth_token_round_trip(db):
    user = auth.register(db, "preauth@example.com", "pw12345")
    token = twofa.issue_preauth(user)
    resolved = twofa.resolve_preauth(db, token)
    assert resolved.id == user.id


def test_preauth_token_rejects_tamper(db):
    user = auth.register(db, "preauthtamper@example.com", "pw12345")
    token = twofa.issue_preauth(user)
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(twofa.InvalidPreauth):
        twofa.resolve_preauth(db, tampered)


def test_preauth_token_expires(db, monkeypatch):
    user = auth.register(db, "preauthexpire@example.com", "pw12345")
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() - twofa.PREAUTH_TTL_SECONDS - 1)
    token = twofa.issue_preauth(user)
    monkeypatch.setattr(time, "time", real_time)
    with pytest.raises(twofa.InvalidPreauth):
        twofa.resolve_preauth(db, token)
