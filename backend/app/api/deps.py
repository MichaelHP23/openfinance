import secrets
import uuid

from fastapi import Cookie, Depends, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.services import auth

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)

LOCAL_USER_EMAIL = "local@openfinance.local"


def _local_user(db: Session) -> User:
    """The single household a LOCAL_MODE install runs as, created on first request.

    Its password is a throwaway random string: the account exists to own rows, and
    is never meant to be logged into.
    """
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = auth.register(db, LOCAL_USER_EMAIL, secrets.token_urlsafe(32))
    return user


def current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if settings.local_mode:
        return _local_user(db)
    user = auth.resolve_session(db, session) if session else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_household(user: User = Depends(current_user)) -> uuid.UUID:
    return user.household_id
