import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user, limiter
from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.schemas.auth import Credentials, PasswordChange, SessionOut, UserOut
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


@router.post("/password", response_model=UserOut)
def change_password(
    body: PasswordChange,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    try:
        token = auth.change_password(db, user, body.current_password, body.new_password)
    except auth.WrongPassword:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    _set_cookie(response, token)
    return _out(user)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    session: str | None = Cookie(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SessionOut]:
    current_hash = auth.hash_token(session) if session else None
    return [
        SessionOut(
            id=s.id, created_at=s.created_at, last_seen_at=s.last_seen_at,
            is_current=s.token_hash == current_hash,
        )
        for s in auth.list_sessions(db, user.id)
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not auth.revoke_session(db, user.id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok"}


@router.delete("/sessions")
def revoke_other_sessions(
    session: str | None = Cookie(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    current_hash = auth.hash_token(session) if session else ""
    return {"revoked": auth.revoke_other_sessions(db, user.id, current_hash)}
