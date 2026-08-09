import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.household import Household
from app.models.session import UserSession
from app.models.user import Role, User

SESSION_TTL = timedelta(days=30)
# Absolute TTL is 30 days; a session unused for this long is revoked sooner, even
# inside that window. Config, not a magic number buried in resolve_session.
IDLE_TIMEOUT = timedelta(days=14)


class EmailTaken(Exception):
    pass


class WrongPassword(Exception):
    pass


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def register(db: Session, email: str, password: str) -> User:
    if db.scalar(select(User).where(User.email == email)):
        raise EmailTaken(email)
    household = Household(name=email)
    db.add(household)
    db.flush()
    user = User(
        household_id=household.id,
        email=email,
        password_hash=hash_password(password),
        role=Role.owner,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def issue_session(db: Session, user: User) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
    )
    db.commit()
    return raw


def resolve_session(db: Session, raw_token: str) -> User | None:
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if not sess:
        return None
    now = datetime.now(UTC)
    if sess.expires_at < now:
        return None
    last_seen = sess.last_seen_at or sess.created_at
    if now - last_seen > IDLE_TIMEOUT:
        return None
    sess.last_seen_at = now
    db.commit()
    return db.get(User, sess.user_id)


def change_password(db: Session, user: User, current_password: str, new_password: str) -> str:
    """Verifies the current password, rotates the credential, and invalidates every
    other session for this user — the "rotation on a privilege-relevant event" the
    spec asks for. Returns a fresh raw token for the caller's own device."""
    if not verify_password(current_password, user.password_hash):
        raise WrongPassword()
    user.password_hash = hash_password(new_password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    return issue_session(db, user)


def list_sessions(db: Session, user_id: uuid.UUID) -> list[UserSession]:
    return list(
        db.scalars(
            select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.created_at.desc())
        )
    )


def revoke_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
    sess = db.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    )
    if not sess:
        return False
    db.delete(sess)
    db.commit()
    return True


def revoke_other_sessions(db: Session, user_id: uuid.UUID, keep_token_hash: str) -> int:
    sessions = list(
        db.scalars(
            select(UserSession).where(
                UserSession.user_id == user_id, UserSession.token_hash != keep_token_hash
            )
        )
    )
    for s in sessions:
        db.delete(s)
    db.commit()
    return len(sessions)
