import uuid
from fastapi import Cookie, Depends, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.services import auth

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)


def current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    user = auth.resolve_session(db, session) if session else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_household(user: User = Depends(current_user)) -> uuid.UUID:
    return user.household_id
