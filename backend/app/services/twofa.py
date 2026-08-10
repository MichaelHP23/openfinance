"""TOTP enrollment and the two-step login it enables. The preauth token between
"password checked" and "code checked" is a stateless HMAC-signed value, not a DB row
— it lives five minutes and needs no cleanup job, matching this app's preference for
the smaller amount of new machinery. See PREAUTH_TTL_SECONDS.
"""

import hmac
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.encryption import decrypt, encrypt
from app.models.user import User
from app.services.totp import generate_secret, provisioning_uri, verify_totp

PREAUTH_TTL_SECONDS = 300


class InvalidPreauth(Exception):
    pass


def _aad(user_id: uuid.UUID) -> bytes:
    return f"{user_id}:totp".encode()


def start_enrollment(db: Session, user: User) -> tuple[str, str]:
    """Stores the secret encrypted immediately, but leaves totp_enabled False —
    enrollment only takes effect once confirm_enrollment proves the user's
    authenticator actually has it, so a half-finished enrollment can't lock anyone
    out of their own login."""
    secret = generate_secret()
    user.totp_secret = encrypt(secret.encode(), aad=_aad(user.id))
    db.commit()
    return secret, provisioning_uri(secret, user.email)


def confirm_enrollment(db: Session, user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    secret = decrypt(user.totp_secret, aad=_aad(user.id)).decode()
    if not verify_totp(secret, code):
        return False
    user.totp_enabled = True
    db.commit()
    return True


def verify_login_code(db: Session, user: User, code: str) -> bool:
    if not user.totp_enabled or not user.totp_secret:
        return False
    secret = decrypt(user.totp_secret, aad=_aad(user.id)).decode()
    return verify_totp(secret, code)


def _sign(user_id: uuid.UUID, ts: int) -> str:
    msg = f"{user_id}.{ts}".encode()
    return hmac.new(settings.app_secret_key.encode(), msg, "sha256").hexdigest()


def issue_preauth(user: User) -> str:
    ts = int(time.time())
    return f"{user.id}.{ts}.{_sign(user.id, ts)}"


def resolve_preauth(db: Session, token: str) -> User:
    try:
        user_id_s, ts_s, sig = token.split(".")
        ts = int(ts_s)
        user_id = uuid.UUID(user_id_s)
    except (ValueError, AttributeError):
        raise InvalidPreauth(token)
    if not hmac.compare_digest(_sign(user_id, ts), sig):
        raise InvalidPreauth(token)
    if time.time() - ts > PREAUTH_TTL_SECONDS:
        raise InvalidPreauth(token)
    user = db.get(User, user_id)
    if user is None:
        raise InvalidPreauth(token)
    return user
