from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user, limiter
from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.schemas.auth import Credentials, UserOut
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "session"


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        max_age=60 * 60 * 24 * 30,
    )


def _out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        role=u.role.value,
        household_id=u.household_id,
        local_mode=settings.local_mode,
    )


@router.post("/register", response_model=UserOut)
@limiter.limit("5/minute")
def register(
    body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    try:
        user = auth.register(db, body.email, body.password)
    except auth.EmailTaken:
        raise HTTPException(status_code=409, detail="Email already registered")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)


@router.post("/login", response_model=UserOut)
@limiter.limit("30/minute")
def login(
    body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    user = auth.authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(COOKIE)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)
