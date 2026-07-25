import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.household import Household
from app.models.session import UserSession
from app.models.user import Role, User

SESSION_TTL = timedelta(days=30)


class EmailTaken(Exception):
    pass


def _hash_token(raw: str) -> str:
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
            token_hash=_hash_token(raw),
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
    )
    db.commit()
    return raw


def resolve_session(db: Session, raw_token: str) -> User | None:
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(raw_token)))
    if not sess or sess.expires_at < datetime.now(UTC):
        return None
    return db.get(User, sess.user_id)
