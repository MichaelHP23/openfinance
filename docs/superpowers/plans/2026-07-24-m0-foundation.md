# M0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OpenFinance foundation — auth, household tenancy, encrypted provider credentials, a `BankProvider` abstraction with a `ManualProvider` impl, and account + transaction core (manual entry + CSV import) — end-to-end and tested.

**Architecture:** Server-authoritative FastAPI backend over PostgreSQL, strict `api → services → (providers + models)` layering. All financial rows scope to `household_id`. React 19 + Vite frontend. Docker Compose runs postgres + redis + api + web.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, argon2-cffi, cryptography (AES-GCM), slowapi, pytest + testcontainers. React 19, Vite, TypeScript, Tailwind, TanStack Query, React Router, React Hook Form, Zod. pytest, vitest, Playwright.

## Global Constraints

- Python 3.13+; Node 20+.
- Money: `NUMERIC(19,4)` in DB, `Decimal` in Python. **Never float for money.**
- Every financial table has a non-null `household_id` FK; every read/write service filters by it.
- PKs are UUID v4.
- PostgreSQL for all environments (dev via Docker). No SQLite.
- Currency column present on accounts + transactions (`char(3)`, default `'USD'`); single-currency enforced in service layer for v1.
- Signed amounts: negative = outflow, positive = inflow.
- Secrets via env only; `.env` gitignored; `.env.example` lists every key.
- No business logic in routers. No ORM queries in routers.
- Provider secrets encrypted at rest via envelope encryption before hitting the DB.
- Lint/type gates: ruff + mypy (backend), eslint + tsc (frontend). Green before milestone close.

---

### Task 1: Backend scaffold, config, Docker Compose

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/core/config.py`, `backend/app/main.py`, `backend/.env.example`, `docker-compose.yml`, `backend/Dockerfile`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.core.config.settings` (Pydantic `Settings`: `database_url: str`, `redis_url: str`, `app_secret_key: str`, `environment: str`). FastAPI app `app.main.app` with `GET /health` → `{"status": "ok"}`.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "openfinance-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlalchemy>=2.0",
  "alembic>=1.14",
  "psycopg[binary]>=3.2",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "argon2-cffi>=23.1",
  "cryptography>=44.0",
  "slowapi>=0.1.9",
  "python-multipart>=0.0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "httpx>=0.27",
  "testcontainers[postgresql]>=4.8", "ruff>=0.8", "mypy>=1.13"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.mypy]
python_version = "3.13"
strict = true

[tool.pytest.ini_options]
addopts = "-v"
```

- [ ] **Step 2: Write `backend/app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://openfinance:openfinance@localhost:5432/openfinance"
    redis_url: str = "redis://localhost:6379/0"
    app_secret_key: str = "dev-only-insecure-change-me-32-bytes!!"
    environment: str = "development"


settings = Settings()
```

- [ ] **Step 3: Write `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="OpenFinance API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Write `backend/.env.example`**

```
DATABASE_URL=postgresql+psycopg://openfinance:openfinance@localhost:5432/openfinance
REDIS_URL=redis://localhost:6379/0
APP_SECRET_KEY=change-me-to-a-random-32-byte-secret
ENVIRONMENT=development
```

- [ ] **Step 5: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: openfinance
      POSTGRES_PASSWORD: openfinance
      POSTGRES_DB: openfinance
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
volumes:
  pgdata:
```

- [ ] **Step 6: Write `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 7: Install and run test**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_health.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend docker-compose.yml
git commit -m "feat: backend scaffold, config, docker-compose, health endpoint"
```

---

### Task 2: DB session + declarative base + UUID/timestamp mixin

**Files:**
- Create: `backend/app/core/db.py`, `backend/app/models/base.py`
- Test: `backend/tests/conftest.py`, `backend/tests/test_db.py`

**Interfaces:**
- Produces: `app.core.db.engine`, `app.core.db.SessionLocal`, `get_db()` FastAPI dependency yielding a `Session`. `app.models.base.Base` (DeclarativeBase). `Base` subclasses get `id: Mapped[UUID]` (pk, default uuid4) and `created_at: Mapped[datetime]` via `UUIDMixin`/`TimestampMixin`.
- Consumes: `settings.database_url` (Task 1).

- [ ] **Step 1: Write `backend/app/core/db.py`**

```python
from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Write `backend/app/models/base.py`**

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 3: Write `backend/tests/conftest.py`** (real Postgres via testcontainers, fresh schema per session)

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer
from app.models.base import Base
import app.models  # noqa: F401  ensure all models imported/registered


@pytest.fixture(scope="session")
def pg_engine():
    with PostgresContainer("postgres:17", driver="psycopg") as pg:
        engine = create_engine(pg.get_connection_url())
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def db(pg_engine):
    conn = pg_engine.connect()
    txn = conn.begin()
    session = sessionmaker(bind=conn, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        txn.rollback()
        conn.close()
```

- [ ] **Step 4: Create `backend/app/models/__init__.py`** (grows as models are added)

```python
# Import every model module so Base.metadata is complete for create_all / Alembic autogen.
```

- [ ] **Step 5: Write `backend/tests/test_db.py`**

```python
from sqlalchemy import text


def test_db_connects(db):
    assert db.execute(text("SELECT 1")).scalar() == 1
```

- [ ] **Step 6: Run test**

Run: `cd backend && pytest tests/test_db.py`
Expected: PASS (testcontainers spins up Postgres).

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/db.py backend/app/models backend/tests/conftest.py backend/tests/test_db.py
git commit -m "feat: db session, declarative base, uuid/timestamp mixins, testcontainers fixtures"
```

---

### Task 3: Envelope encryption core

**Files:**
- Create: `backend/app/core/encryption.py`
- Test: `backend/tests/test_encryption.py`

**Interfaces:**
- Produces: `encrypt(plaintext: bytes) -> bytes` and `decrypt(blob: bytes) -> bytes`. Blob layout: `wrapped_dek(nonce||ct) || nonce || ciphertext`, DEK wrapped by KEK derived from `settings.app_secret_key`. Both use AES-256-GCM.
- Consumes: `settings.app_secret_key` (Task 1).

- [ ] **Step 1: Write failing test `backend/tests/test_encryption.py`**

```python
import pytest
from app.core.encryption import encrypt, decrypt


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
    with pytest.raises(Exception):
        decrypt(bytes(blob))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_encryption.py`
Expected: FAIL — module `app.core.encryption` not found.

- [ ] **Step 3: Write `backend/app/core/encryption.py`**

```python
import hashlib
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.config import settings

_KEK = hashlib.sha256(settings.app_secret_key.encode()).digest()  # 32-byte KEK


def _seal(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _open(key: bytes, blob: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


def encrypt(plaintext: bytes) -> bytes:
    dek = os.urandom(32)
    wrapped = _seal(_KEK, dek)                       # 12 + 32 + 16 = 60 bytes
    return len(wrapped).to_bytes(2, "big") + wrapped + _seal(dek, plaintext)


def decrypt(blob: bytes) -> bytes:
    wlen = int.from_bytes(blob[:2], "big")
    wrapped, body = blob[2 : 2 + wlen], blob[2 + wlen :]
    dek = _open(_KEK, wrapped)
    return _open(dek, body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_encryption.py`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/encryption.py backend/tests/test_encryption.py
git commit -m "feat: envelope encryption (AES-GCM) for provider credentials"
```

---

### Task 4: Household + User + Session models + password hashing + Alembic

**Files:**
- Create: `backend/app/models/household.py`, `backend/app/models/user.py`, `backend/app/models/session.py`, `backend/app/core/security.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Produces:
  - `Household(id, name, created_at)`.
  - `User(id, household_id, email, password_hash, role, created_at)`, `role` enum `owner|member|viewer`.
  - `UserSession(id, user_id, token_hash, expires_at, created_at)`.
  - `app.core.security.hash_password(pw: str) -> str`, `verify_password(pw: str, hash: str) -> bool` (argon2id).
- Consumes: `Base`, mixins (Task 2).

- [ ] **Step 1: Write `backend/app/models/household.py`**

```python
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Household(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column()
```

- [ ] **Step 2: Write `backend/app/models/user.py`**

```python
import enum
import uuid
from sqlalchemy import ForeignKey, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Role(str, enum.Enum):
    owner = "owner"
    member = "member"
    viewer = "viewer"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column()
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.owner)
```

- [ ] **Step 3: Write `backend/app/models/session.py`**

```python
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class UserSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.household import Household  # noqa: F401
from app.models.user import User, Role  # noqa: F401
from app.models.session import UserSession  # noqa: F401
```

- [ ] **Step 5: Write `backend/app/core/security.py`**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hash_: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except VerifyMismatchError:
        return False
```

- [ ] **Step 6: Write failing test `backend/tests/test_security.py`**

```python
from app.core.security import hash_password, verify_password


def test_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)
```

- [ ] **Step 7: Run test**

Run: `pytest tests/test_security.py`
Expected: PASS.

- [ ] **Step 8: Initialize Alembic and generate migration**

Run:
```bash
cd backend && alembic init migrations
```
Then edit `backend/alembic.ini` `sqlalchemy.url` to read from env, and set `backend/migrations/env.py` `target_metadata`:

```python
# migrations/env.py — key edits
from app.core.config import settings
from app.models.base import Base
import app.models  # noqa: F401  register all models
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata
```

Generate + apply:
```bash
alembic revision --autogenerate -m "households, users, sessions"
alembic upgrade head
```
Expected: migration creates `households`, `users`, `sessions`, `role` enum.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/app/core/security.py backend/tests/test_security.py backend/alembic.ini backend/migrations
git commit -m "feat: household/user/session models, argon2 hashing, alembic migrations"
```

---

### Task 5: Auth service (register + login + session issue/validate)

**Files:**
- Create: `backend/app/services/auth.py`, `backend/app/schemas/auth.py`
- Test: `backend/tests/test_auth_service.py`

**Interfaces:**
- Produces (`app.services.auth`):
  - `register(db, email: str, password: str) -> User` — creates a Household(name=email) + owner User; raises `EmailTaken` if email exists.
  - `authenticate(db, email, password) -> User | None`.
  - `issue_session(db, user) -> str` — returns raw opaque token (caller sets cookie); stores only `sha256(token)`.
  - `resolve_session(db, raw_token) -> User | None` — validates hash + expiry.
  - `EmailTaken(Exception)`.
- Consumes: `hash_password`/`verify_password` (Task 4), `User`, `Household`, `UserSession`.

- [ ] **Step 1: Write failing test `backend/tests/test_auth_service.py`**

```python
import pytest
from app.services import auth


def test_register_creates_household_and_owner(db):
    user = auth.register(db, "a@example.com", "pw12345")
    assert user.email == "a@example.com"
    assert user.role.value == "owner"
    assert user.household_id is not None


def test_register_duplicate_email_raises(db):
    auth.register(db, "a@example.com", "pw12345")
    with pytest.raises(auth.EmailTaken):
        auth.register(db, "a@example.com", "other")


def test_authenticate_ok_and_bad(db):
    auth.register(db, "a@example.com", "pw12345")
    assert auth.authenticate(db, "a@example.com", "pw12345") is not None
    assert auth.authenticate(db, "a@example.com", "nope") is None
    assert auth.authenticate(db, "missing@example.com", "pw") is None


def test_session_issue_and_resolve(db):
    user = auth.register(db, "a@example.com", "pw12345")
    token = auth.issue_session(db, user)
    resolved = auth.resolve_session(db, token)
    assert resolved is not None and resolved.id == user.id
    assert auth.resolve_session(db, "garbage") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth_service.py`
Expected: FAIL — `app.services.auth` missing.

- [ ] **Step 3: Write `backend/app/services/auth.py`**

```python
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import hash_password, verify_password
from app.models.household import Household
from app.models.user import User, Role
from app.models.session import UserSession

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
            expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        )
    )
    db.commit()
    return raw


def resolve_session(db: Session, raw_token: str) -> User | None:
    sess = db.scalar(
        select(UserSession).where(UserSession.token_hash == _hash_token(raw_token))
    )
    if not sess or sess.expires_at < datetime.now(timezone.utc):
        return None
    return db.get(User, sess.user_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth_service.py`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auth.py backend/tests/test_auth_service.py
git commit -m "feat: auth service (register/login/session issue+resolve)"
```

---

### Task 6: Auth router + session cookie + `current_user`/`require_household` deps + rate limiting

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Produces:
  - `POST /auth/register` `{email,password}` → sets `session` cookie, returns `{id,email,role,household_id}`.
  - `POST /auth/login` same shape; `POST /auth/logout`; `GET /auth/me`.
  - `app.api.deps.current_user(...) -> User` (401 if no/invalid cookie).
  - `app.api.deps.require_household(...) -> uuid.UUID` (returns `current_user.household_id`).
  - `app.api.deps.get_limiter()` slowapi limiter (Redis-backed).
- Consumes: `auth` service (Task 5), `get_db` (Task 2).

- [ ] **Step 1: Write `backend/app/api/deps.py`**

```python
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
```

- [ ] **Step 2: Write `backend/app/schemas/auth.py`**

```python
import uuid
from pydantic import BaseModel, EmailStr


class Credentials(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    household_id: uuid.UUID
```

- [ ] **Step 3: Write `backend/app/api/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response
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
        COOKIE, token, httponly=True, samesite="lax",
        secure=settings.environment != "development", max_age=60 * 60 * 24 * 30,
    )


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role.value, household_id=u.household_id)


@router.post("/register", response_model=UserOut)
@limiter.limit("5/minute")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth.register(db, body.email, body.password)
    except auth.EmailTaken:
        raise HTTPException(status_code=409, detail="Email already registered")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)


@router.post("/login", response_model=UserOut)
@limiter.limit("10/minute")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    user = auth.authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return _out(user)
```

Note: slowapi `@limiter.limit` requires the endpoint to accept `request: Request` OR the app to use its middleware. Add `request: Request` param to `register`/`login` signatures if slowapi raises; wire the limiter in Step 4.

- [ ] **Step 4: Wire router + limiter in `backend/app/main.py`**

```python
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.deps import limiter
from app.api import auth

app = FastAPI(title="OpenFinance API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Write test `backend/tests/test_auth_api.py`** (override `get_db` to use the transactional `db` fixture)

```python
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db


def client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_register_login_me_flow(db):
    c = client(db)
    r = c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["email"] == "a@example.com"
    assert "session" in r.cookies

    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


def test_me_requires_auth(db):
    c = TestClient(app)  # no cookie
    app.dependency_overrides[get_db] = lambda: db
    assert c.get("/auth/me").status_code == 401


def test_duplicate_register_conflicts(db):
    c = client(db)
    c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    r = c.post("/auth/register", json={"email": "a@example.com", "password": "x"})
    assert r.status_code == 409
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_auth_api.py`
Expected: PASS. If slowapi errors on missing `Request`, add `request: Request` to `register`/`login` and disable limits in tests via `app.state.limiter.enabled = False`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api backend/app/schemas/auth.py backend/app/main.py backend/tests/test_auth_api.py
git commit -m "feat: auth API (register/login/logout/me), session cookie, deps, rate limiting"
```

---

### Task 7: Provider abstraction + DTOs + ManualProvider + provider_connections model

**Files:**
- Create: `backend/app/providers/base.py`, `backend/app/providers/manual.py`, `backend/app/models/connection.py`
- Modify: `backend/app/models/__init__.py`, Alembic migration
- Test: `backend/tests/test_providers.py`, `backend/tests/test_connection_encryption.py`

**Interfaces:**
- Produces:
  - DTOs `AccountDTO`, `TxnDTO` (dataclasses).
  - `BankProvider(Protocol)` with `name`, `link_account`, `fetch_accounts`, `fetch_transactions`.
  - `ManualProvider` — trivial impl; `link_account` stores encrypted creds and returns the connection.
  - `ProviderConnection(id, household_id, provider, encrypted_credentials: bytes, status, last_synced_at)`.
  - Helpers `set_credentials(conn, dict)` / `get_credentials(conn) -> dict` using Task 3 encryption + JSON.
- Consumes: `encrypt`/`decrypt` (Task 3).

- [ ] **Step 1: Write `backend/app/models/connection.py`**

```python
import enum
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, Enum, LargeBinary, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Provider(str, enum.Enum):
    manual = "manual"
    plaid = "plaid"


class ConnStatus(str, enum.Enum):
    active = "active"
    error = "error"
    disconnected = "disconnected"


class ProviderConnection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "provider_connections"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="provider"))
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[ConnStatus] = mapped_column(
        Enum(ConnStatus, name="conn_status"), default=ConnStatus.active
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Write `backend/app/providers/base.py`**

```python
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from app.core.encryption import encrypt, decrypt
from app.models.connection import ProviderConnection


@dataclass
class AccountDTO:
    external_id: str
    name: str
    type: str
    currency: str
    balance: Decimal


@dataclass
class TxnDTO:
    external_id: str
    account_external_id: str
    posted_at: datetime
    amount: Decimal
    currency: str
    merchant_raw: str


class BankProvider(Protocol):
    name: str

    def link_account(self, household_id: uuid.UUID, credentials: dict) -> ProviderConnection: ...
    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]: ...
    def fetch_transactions(self, conn: ProviderConnection, since: datetime | None) -> list[TxnDTO]: ...


def set_credentials(conn: ProviderConnection, creds: dict) -> None:
    conn.encrypted_credentials = encrypt(json.dumps(creds).encode())


def get_credentials(conn: ProviderConnection) -> dict:
    return json.loads(decrypt(conn.encrypted_credentials).decode())
```

- [ ] **Step 3: Write `backend/app/providers/manual.py`**

```python
import uuid
from datetime import datetime
from app.models.connection import ProviderConnection, Provider
from app.providers.base import AccountDTO, TxnDTO, set_credentials


class ManualProvider:
    name = "manual"

    def link_account(self, household_id: uuid.UUID, credentials: dict) -> ProviderConnection:
        conn = ProviderConnection(household_id=household_id, provider=Provider.manual)
        set_credentials(conn, credentials or {"kind": "manual"})
        return conn

    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]:
        return []  # manual accounts are user-created, not fetched

    def fetch_transactions(self, conn: ProviderConnection, since: datetime | None) -> list[TxnDTO]:
        return []
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`** — add `from app.models.connection import ProviderConnection, Provider, ConnStatus  # noqa: F401`

- [ ] **Step 5: Write test `backend/tests/test_providers.py`**

```python
import uuid
from app.providers.manual import ManualProvider
from app.providers.base import BankProvider, get_credentials


def test_manual_provider_satisfies_protocol():
    p: BankProvider = ManualProvider()  # type: ignore[assignment]
    assert p.name == "manual"


def test_link_account_encrypts_and_roundtrips():
    conn = ManualProvider().link_account(uuid.uuid4(), {"secret": "abc"})
    assert conn.encrypted_credentials != b'{"secret": "abc"}'
    assert get_credentials(conn) == {"secret": "abc"}
```

- [ ] **Step 6: Run test**

Run: `pytest tests/test_providers.py`
Expected: PASS.

- [ ] **Step 7: Generate + apply migration**

Run:
```bash
cd backend && alembic revision --autogenerate -m "provider_connections" && alembic upgrade head
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/providers backend/app/models/connection.py backend/app/models/__init__.py backend/tests/test_providers.py backend/migrations
git commit -m "feat: BankProvider protocol, DTOs, ManualProvider, encrypted provider_connections"
```

---

### Task 8: Category + Account models & service (tenancy-scoped)

**Files:**
- Create: `backend/app/models/category.py`, `backend/app/models/account.py`, `backend/app/services/accounts.py`, `backend/app/schemas/account.py`, `backend/app/api/accounts.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`, migration
- Test: `backend/tests/test_accounts.py`, `backend/tests/test_tenancy.py`

**Interfaces:**
- Produces:
  - `Category(id, household_id?, name, parent_id?)`.
  - `Account(id, household_id, connection_id?, type, name, institution?, currency, balance, is_manual)`; `AccountType` enum from spec.
  - `services.accounts.create(db, household_id, data) -> Account`, `list_for(db, household_id) -> list[Account]`, `get(db, household_id, account_id) -> Account` (404/None if other household).
  - `POST /accounts`, `GET /accounts`.
- Consumes: `require_household` (Task 6).

- [ ] **Step 1: Write `backend/app/models/category.py`**

```python
import uuid
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Category(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "categories"
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), nullable=True, index=True
    )  # null = system default
    name: Mapped[str] = mapped_column()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
```

- [ ] **Step 2: Write `backend/app/models/account.py`**

```python
import enum
import uuid
from decimal import Decimal
from sqlalchemy import ForeignKey, Enum, Numeric, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class AccountType(str, enum.Enum):
    checking = "checking"; savings = "savings"; credit_card = "credit_card"
    loan = "loan"; investment = "investment"; crypto = "crypto"
    cash = "cash"; asset = "asset"; liability = "liability"


class Account(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "accounts"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_connections.id"), nullable=True
    )
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"))
    name: Mapped[str] = mapped_column()
    institution: Mapped[str | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 3: Write `backend/app/schemas/account.py`**

```python
import uuid
from decimal import Decimal
from pydantic import BaseModel


class AccountCreate(BaseModel):
    type: str
    name: str
    institution: str | None = None
    currency: str = "USD"
    balance: Decimal = Decimal("0")


class AccountOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    institution: str | None
    currency: str
    balance: Decimal
    is_manual: bool
    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Write `backend/app/services/accounts.py`**

```python
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.account import Account, AccountType
from app.schemas.account import AccountCreate

SUPPORTED_CURRENCY = "USD"


def create(db: Session, household_id: uuid.UUID, data: AccountCreate) -> Account:
    if data.currency != SUPPORTED_CURRENCY:
        raise ValueError("Only USD supported in v1")
    acct = Account(
        household_id=household_id, type=AccountType(data.type), name=data.name,
        institution=data.institution, currency=data.currency, balance=data.balance,
        is_manual=True,
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def list_for(db: Session, household_id: uuid.UUID) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.household_id == household_id)))


def get(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> Account | None:
    return db.scalar(
        select(Account).where(Account.id == account_id, Account.household_id == household_id)
    )
```

- [ ] **Step 5: Write `backend/app/api/accounts.py`**

```python
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.account import AccountCreate, AccountOut
from app.services import accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut)
def create_account(
    body: AccountCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
):
    return accounts.create(db, hid, body)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
):
    return accounts.list_for(db, hid)
```

- [ ] **Step 6: Register router** — add `from app.api import accounts` and `app.include_router(accounts.router)` in `main.py`. Update `models/__init__.py` with Category + Account imports.

- [ ] **Step 7: Write test `backend/tests/test_accounts.py`**

```python
import uuid
from decimal import Decimal
from app.services import accounts
from app.schemas.account import AccountCreate


def test_create_and_list(db):
    hid = uuid.uuid4()
    accounts.create(db, hid, AccountCreate(type="checking", name="Main", balance=Decimal("100.50")))
    rows = accounts.list_for(db, hid)
    assert len(rows) == 1
    assert rows[0].balance == Decimal("100.5000")


def test_rejects_non_usd(db):
    import pytest
    with pytest.raises(ValueError):
        accounts.create(db, uuid.uuid4(), AccountCreate(type="cash", name="x", currency="EUR"))
```

- [ ] **Step 8: Write tenancy test `backend/tests/test_tenancy.py`**

```python
import uuid
from app.services import accounts
from app.schemas.account import AccountCreate


def test_accounts_isolated_by_household(db):
    h1, h2 = uuid.uuid4(), uuid.uuid4()
    a = accounts.create(db, h1, AccountCreate(type="checking", name="H1"))
    accounts.create(db, h2, AccountCreate(type="checking", name="H2"))

    assert {x.name for x in accounts.list_for(db, h1)} == {"H1"}
    assert accounts.get(db, h2, a.id) is None       # cannot read across household
    assert accounts.get(db, h1, a.id) is not None
```

- [ ] **Step 9: Run tests + migration**

Run: `pytest tests/test_accounts.py tests/test_tenancy.py` → PASS.
Run: `alembic revision --autogenerate -m "categories, accounts" && alembic upgrade head`

- [ ] **Step 10: Commit**

```bash
git add backend/app/models backend/app/services/accounts.py backend/app/schemas/account.py backend/app/api/accounts.py backend/app/main.py backend/tests/test_accounts.py backend/tests/test_tenancy.py backend/migrations
git commit -m "feat: account+category models, tenancy-scoped account service/API, isolation tests"
```

---

### Task 9: Transaction model + service (CRUD, filter, tenancy) + API

**Files:**
- Create: `backend/app/models/transaction.py`, `backend/app/services/transactions.py`, `backend/app/schemas/transaction.py`, `backend/app/api/transactions.py`
- Modify: `backend/app/models/__init__.py`, `main.py`, migration
- Test: `backend/tests/test_transactions.py`

**Interfaces:**
- Produces:
  - `Transaction(id, household_id, account_id, posted_at, amount, currency, merchant_raw, merchant_normalized?, category_id?, notes?, external_id?)`.
  - `services.transactions`: `create`, `list_for(db, household_id, *, account_id=None, since=None, until=None, search=None)`, `get`, `update`, `delete` — all household-scoped; each verifies the referenced account belongs to the household.
  - `POST /transactions`, `GET /transactions` (query filters), `PATCH /transactions/{id}`, `DELETE /transactions/{id}`.
- Consumes: `accounts.get` (Task 8), `require_household`.

- [ ] **Step 1: Write `backend/app/models/transaction.py`**

```python
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), index=True
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    merchant_raw: Mapped[str] = mapped_column()
    merchant_normalized: Mapped[str | None] = mapped_column(nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(nullable=True)
    external_id: Mapped[str | None] = mapped_column(nullable=True, index=True)
```

- [ ] **Step 2: Write `backend/app/schemas/transaction.py`**

```python
import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class TxnCreate(BaseModel):
    account_id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    merchant_raw: str
    currency: str = "USD"
    category_id: uuid.UUID | None = None
    notes: str | None = None


class TxnUpdate(BaseModel):
    merchant_normalized: str | None = None
    category_id: uuid.UUID | None = None
    notes: str | None = None


class TxnOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    currency: str
    merchant_raw: str
    merchant_normalized: str | None
    category_id: uuid.UUID | None
    notes: str | None
    model_config = {"from_attributes": True}
```

- [ ] **Step 3: Write `backend/app/services/transactions.py`**

```python
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.transaction import Transaction
from app.schemas.transaction import TxnCreate, TxnUpdate
from app.services import accounts


class AccountNotInHousehold(Exception):
    pass


def _assert_account(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> None:
    if accounts.get(db, household_id, account_id) is None:
        raise AccountNotInHousehold(str(account_id))


def create(db: Session, household_id: uuid.UUID, data: TxnCreate) -> Transaction:
    _assert_account(db, household_id, data.account_id)
    txn = Transaction(
        household_id=household_id, account_id=data.account_id, posted_at=data.posted_at,
        amount=data.amount, currency=data.currency, merchant_raw=data.merchant_raw,
        category_id=data.category_id, notes=data.notes,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def list_for(
    db: Session, household_id: uuid.UUID, *,
    account_id: uuid.UUID | None = None, since: datetime | None = None,
    until: datetime | None = None, search: str | None = None,
) -> list[Transaction]:
    q = select(Transaction).where(Transaction.household_id == household_id)
    if account_id:
        q = q.where(Transaction.account_id == account_id)
    if since:
        q = q.where(Transaction.posted_at >= since)
    if until:
        q = q.where(Transaction.posted_at <= until)
    if search:
        q = q.where(Transaction.merchant_raw.ilike(f"%{search}%"))
    return list(db.scalars(q.order_by(Transaction.posted_at.desc())))


def get(db: Session, household_id: uuid.UUID, txn_id: uuid.UUID) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(
            Transaction.id == txn_id, Transaction.household_id == household_id
        )
    )


def update(db: Session, household_id: uuid.UUID, txn_id: uuid.UUID, data: TxnUpdate) -> Transaction | None:
    txn = get(db, household_id, txn_id)
    if not txn:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(txn, field, value)
    db.commit()
    db.refresh(txn)
    return txn


def delete(db: Session, household_id: uuid.UUID, txn_id: uuid.UUID) -> bool:
    txn = get(db, household_id, txn_id)
    if not txn:
        return False
    db.delete(txn)
    db.commit()
    return True
```

- [ ] **Step 4: Write `backend/app/api/transactions.py`**

```python
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.transaction import TxnCreate, TxnUpdate, TxnOut
from app.services import transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TxnOut)
def create_txn(body: TxnCreate, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)):
    try:
        return transactions.create(db, hid, body)
    except transactions.AccountNotInHousehold:
        raise HTTPException(status_code=404, detail="Account not found")


@router.get("", response_model=list[TxnOut])
def list_txns(
    account_id: uuid.UUID | None = None, since: datetime | None = None,
    until: datetime | None = None, search: str | None = None,
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db),
):
    return transactions.list_for(db, hid, account_id=account_id, since=since, until=until, search=search)


@router.patch("/{txn_id}", response_model=TxnOut)
def update_txn(txn_id: uuid.UUID, body: TxnUpdate, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)):
    txn = transactions.update(db, hid, txn_id, body)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.delete("/{txn_id}")
def delete_txn(txn_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)):
    if not transactions.delete(db, hid, txn_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"status": "ok"}
```

- [ ] **Step 5: Register router + model** — `main.py` include `transactions.router`; `models/__init__.py` import `Transaction`.

- [ ] **Step 6: Write test `backend/tests/test_transactions.py`**

```python
import uuid
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from app.services import accounts, transactions
from app.schemas.account import AccountCreate
from app.schemas.transaction import TxnCreate, TxnUpdate


def _acct(db, hid):
    return accounts.create(db, hid, AccountCreate(type="checking", name="Main"))


def test_create_list_filter(db):
    hid = uuid.uuid4()
    acct = _acct(db, hid)
    transactions.create(db, hid, TxnCreate(account_id=acct.id, posted_at=datetime(2026,1,1,tzinfo=timezone.utc), amount=Decimal("-9.99"), merchant_raw="Starbucks"))
    transactions.create(db, hid, TxnCreate(account_id=acct.id, posted_at=datetime(2026,2,1,tzinfo=timezone.utc), amount=Decimal("-4.50"), merchant_raw="Amazon"))
    assert len(transactions.list_for(db, hid)) == 2
    assert len(transactions.list_for(db, hid, search="star")) == 1
    assert len(transactions.list_for(db, hid, since=datetime(2026,1,15,tzinfo=timezone.utc))) == 1


def test_create_rejects_foreign_account(db):
    hid, other = uuid.uuid4(), uuid.uuid4()
    acct = _acct(db, other)
    with pytest.raises(transactions.AccountNotInHousehold):
        transactions.create(db, hid, TxnCreate(account_id=acct.id, posted_at=datetime.now(timezone.utc), amount=Decimal("1"), merchant_raw="x"))


def test_update_and_delete(db):
    hid = uuid.uuid4()
    acct = _acct(db, hid)
    t = transactions.create(db, hid, TxnCreate(account_id=acct.id, posted_at=datetime.now(timezone.utc), amount=Decimal("-1"), merchant_raw="Cafe"))
    transactions.update(db, hid, t.id, TxnUpdate(notes="lunch", merchant_normalized="Cafe Inc"))
    assert transactions.get(db, hid, t.id).notes == "lunch"
    assert transactions.delete(db, hid, t.id) is True
    assert transactions.get(db, hid, t.id) is None


def test_txn_tenancy_isolation(db):
    h1, h2 = uuid.uuid4(), uuid.uuid4()
    acct = _acct(db, h1)
    t = transactions.create(db, h1, TxnCreate(account_id=acct.id, posted_at=datetime.now(timezone.utc), amount=Decimal("-1"), merchant_raw="X"))
    assert transactions.get(db, h2, t.id) is None
    assert transactions.list_for(db, h2) == []
```

- [ ] **Step 7: Run tests + migration**

Run: `pytest tests/test_transactions.py` → PASS.
Run: `alembic revision --autogenerate -m "transactions" && alembic upgrade head`

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/transaction.py backend/app/services/transactions.py backend/app/schemas/transaction.py backend/app/api/transactions.py backend/app/main.py backend/app/models/__init__.py backend/tests/test_transactions.py backend/migrations
git commit -m "feat: transaction model, tenancy-scoped CRUD+filter service/API, isolation tests"
```

---

### Task 10: CSV transaction import

**Files:**
- Create: `backend/app/services/csv_import.py`, `backend/app/api/imports.py`
- Modify: `main.py`
- Test: `backend/tests/test_csv_import.py`

**Interfaces:**
- Produces:
  - `services.csv_import.import_csv(db, household_id, account_id, raw: str) -> ImportResult(imported: int, skipped: int)`. Expects columns `date,amount,merchant` (header row). Skips rows whose `(account_id, external_id)` already present, where `external_id = sha256(date|amount|merchant)`.
  - `POST /accounts/{account_id}/import` (multipart file) → `{imported, skipped}`.
- Consumes: `transactions.create` semantics, `accounts.get`.

- [ ] **Step 1: Write failing test `backend/tests/test_csv_import.py`**

```python
import uuid
from app.services import accounts, csv_import, transactions
from app.schemas.account import AccountCreate

CSV = "date,amount,merchant\n2026-01-01,-9.99,Starbucks\n2026-01-02,-4.50,Amazon\n"


def test_import_creates_transactions(db):
    hid = uuid.uuid4()
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Main"))
    res = csv_import.import_csv(db, hid, acct.id, CSV)
    assert res.imported == 2 and res.skipped == 0
    assert len(transactions.list_for(db, hid)) == 2


def test_reimport_is_deduped(db):
    hid = uuid.uuid4()
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Main"))
    csv_import.import_csv(db, hid, acct.id, CSV)
    res = csv_import.import_csv(db, hid, acct.id, CSV)
    assert res.imported == 0 and res.skipped == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_csv_import.py`
Expected: FAIL — `app.services.csv_import` missing.

- [ ] **Step 3: Write `backend/app/services/csv_import.py`**

```python
import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.transaction import Transaction
from app.services import accounts


@dataclass
class ImportResult:
    imported: int
    skipped: int


def _external_id(date: str, amount: str, merchant: str) -> str:
    return hashlib.sha256(f"{date}|{amount}|{merchant}".encode()).hexdigest()


def import_csv(db: Session, household_id: uuid.UUID, account_id: uuid.UUID, raw: str) -> ImportResult:
    if accounts.get(db, household_id, account_id) is None:
        raise ValueError("Account not in household")
    existing = set(
        db.scalars(select(Transaction.external_id).where(Transaction.account_id == account_id))
    )
    imported = skipped = 0
    for row in csv.DictReader(io.StringIO(raw)):
        ext = _external_id(row["date"], row["amount"], row["merchant"])
        if ext in existing:
            skipped += 1
            continue
        db.add(Transaction(
            household_id=household_id, account_id=account_id,
            posted_at=datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc),
            amount=Decimal(row["amount"]), currency="USD",
            merchant_raw=row["merchant"], external_id=ext,
        ))
        existing.add(ext)
        imported += 1
    db.commit()
    return ImportResult(imported=imported, skipped=skipped)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_csv_import.py`
Expected: PASS.

- [ ] **Step 5: Write `backend/app/api/imports.py`**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import require_household
from app.core.db import get_db
from app.services import csv_import

router = APIRouter(prefix="/accounts", tags=["imports"])


@router.post("/{account_id}/import")
async def import_transactions(
    account_id: uuid.UUID, file: UploadFile,
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db),
):
    raw = (await file.read()).decode()
    try:
        res = csv_import.import_csv(db, hid, account_id, raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"imported": res.imported, "skipped": res.skipped}
```

- [ ] **Step 6: Register router** — include `imports.router` in `main.py`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/csv_import.py backend/app/api/imports.py backend/app/main.py backend/tests/test_csv_import.py
git commit -m "feat: CSV transaction import with dedup"
```

---

### Task 11: Backend quality gate + full suite

**Files:**
- Modify: any files flagged by ruff/mypy.
- Create: `backend/Dockerfile`

**Interfaces:** none (hardening task).

- [ ] **Step 1: Run full test suite**

Run: `cd backend && pytest`
Expected: all tests PASS.

- [ ] **Step 2: Run ruff**

Run: `ruff check app tests && ruff format --check app tests`
Fix reported issues. Re-run until clean.

- [ ] **Step 3: Run mypy**

Run: `mypy app`
Fix type errors. Re-run until clean.

- [ ] **Step 4: Write `backend/Dockerfile`**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 5: Add api + web services to `docker-compose.yml`**

```yaml
  api:
    build: ./backend
    env_file: ./backend/.env
    depends_on: [postgres, redis]
    ports: ["8000:8000"]
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

- [ ] **Step 6: Commit**

```bash
git add backend docker-compose.yml
git commit -m "chore: backend lint/type clean, Dockerfile, api compose service"
```

---

### Task 12: Frontend scaffold + API client + auth pages

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.js`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/api/client.ts`, `frontend/src/auth/LoginPage.tsx`, `frontend/src/auth/RegisterPage.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `apiFetch(path, opts)` (fetch wrapper, `credentials: "include"`, throws on non-2xx). Router with `/login`, `/register`, `/` (protected). TanStack Query provider.
- Consumes: backend `/auth/*` (Task 6).

- [ ] **Step 1: Scaffold**

Run:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install @tanstack/react-query react-router-dom react-hook-form zod @hookform/resolvers recharts
npm install -D tailwindcss @tailwindcss/postcss vitest @testing-library/react jsdom @playwright/test
```

- [ ] **Step 2: Write `frontend/src/api/client.ts`**

```ts
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...opts.headers },
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.status === 204 ? (undefined as T) : res.json();
}
```

- [ ] **Step 3: Write `frontend/src/api/client.test.ts`**

```ts
import { describe, it, expect, vi } from "vitest";
import { apiFetch } from "./client";

describe("apiFetch", () => {
  it("throws detail on error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 401 })));
    await expect(apiFetch("/x")).rejects.toThrow("nope");
  });
  it("returns json on ok", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ a: 1 }), { status: 200 })));
    expect(await apiFetch("/x")).toEqual({ a: 1 });
  });
});
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS (add `test: { environment: "jsdom" }` to `vite.config.ts`).

- [ ] **Step 5: Write `frontend/src/auth/RegisterPage.tsx`** (React Hook Form + Zod)

```tsx
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useNavigate, Link } from "react-router-dom";
import { apiFetch } from "../api/client";

const schema = z.object({ email: z.string().email(), password: z.string().min(6) });
type Form = z.infer<typeof schema>;

export function RegisterPage() {
  const nav = useNavigate();
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } =
    useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: Form) => {
    try {
      await apiFetch("/auth/register", { method: "POST", body: JSON.stringify(data) });
      nav("/");
    } catch (e) {
      setError("email", { message: (e as Error).message });
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="mx-auto mt-24 flex max-w-sm flex-col gap-3 p-4">
      <h1 className="text-xl font-semibold">Create account</h1>
      <input className="rounded border p-2" placeholder="Email" {...register("email")} />
      {errors.email && <span className="text-sm text-red-600">{errors.email.message}</span>}
      <input className="rounded border p-2" type="password" placeholder="Password" {...register("password")} />
      {errors.password && <span className="text-sm text-red-600">{errors.password.message}</span>}
      <button disabled={isSubmitting} className="rounded bg-black p-2 text-white">Sign up</button>
      <Link to="/login" className="text-sm text-blue-600">Have an account? Log in</Link>
    </form>
  );
}
```

- [ ] **Step 6: Write `frontend/src/auth/LoginPage.tsx`** (same shape, `POST /auth/login`, link to `/register`, heading "Log in"). Reuse the RegisterPage structure with the endpoint and copy changed.

- [ ] **Step 7: Write `frontend/src/App.tsx`** (router + query provider + protected route)

```tsx
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { apiFetch } from "./api/client";
import { LoginPage } from "./auth/LoginPage";
import { RegisterPage } from "./auth/RegisterPage";
import { Dashboard } from "./Dashboard";

const qc = new QueryClient();

function Protected({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["me"], queryFn: () => apiFetch("/auth/me"), retry: false,
  });
  if (isLoading) return <div className="p-8">Loading…</div>;
  if (isError || !data) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: frontend scaffold, api client, auth pages, protected routing"
```

---

### Task 13: Frontend accounts + transactions UI + CSV upload

**Files:**
- Create: `frontend/src/Dashboard.tsx`, `frontend/src/accounts/AccountList.tsx`, `frontend/src/accounts/NewAccountForm.tsx`, `frontend/src/transactions/TransactionList.tsx`, `frontend/src/transactions/NewTransactionForm.tsx`, `frontend/src/transactions/CsvUpload.tsx`
- Test: `frontend/src/transactions/TransactionList.test.tsx`

**Interfaces:**
- Produces: `Dashboard` composing account list + new-account form + transaction list + new-txn form + CSV upload. All via TanStack Query against `/accounts` and `/transactions`.
- Consumes: `apiFetch` (Task 12).

- [ ] **Step 1: Write `frontend/src/accounts/AccountList.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Account = { id: string; name: string; type: string; balance: string; currency: string };

export function AccountList() {
  const { data = [] } = useQuery({ queryKey: ["accounts"], queryFn: () => apiFetch<Account[]>("/accounts") });
  return (
    <ul className="divide-y rounded border">
      {data.map((a) => (
        <li key={a.id} className="flex justify-between p-3">
          <span>{a.name} <em className="text-gray-500">({a.type})</em></span>
          <span>{a.currency} {a.balance}</span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 2: Write `frontend/src/accounts/NewAccountForm.tsx`** (React Hook Form → `POST /accounts`, invalidate `["accounts"]` on success)

```tsx
import { useForm } from "react-hook-form";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Form = { name: string; type: string; balance: string };

export function NewAccountForm() {
  const qc = useQueryClient();
  const { register, handleSubmit, reset } = useForm<Form>({ defaultValues: { type: "checking", balance: "0" } });
  const mut = useMutation({
    mutationFn: (f: Form) => apiFetch("/accounts", { method: "POST", body: JSON.stringify(f) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); reset(); },
  });
  return (
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex gap-2">
      <input className="rounded border p-2" placeholder="Name" {...register("name")} />
      <select className="rounded border p-2" {...register("type")}>
        {["checking","savings","credit_card","cash","investment","crypto","loan","asset","liability"].map(t => <option key={t}>{t}</option>)}
      </select>
      <input className="rounded border p-2 w-28" placeholder="Balance" {...register("balance")} />
      <button className="rounded bg-black px-3 text-white">Add</button>
    </form>
  );
}
```

- [ ] **Step 3: Write `frontend/src/transactions/TransactionList.tsx`** (query `/transactions`, search box drives `?search=`)

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Txn = { id: string; posted_at: string; merchant_raw: string; amount: string; currency: string };

export function TransactionList() {
  const [search, setSearch] = useState("");
  const { data = [] } = useQuery({
    queryKey: ["transactions", search],
    queryFn: () => apiFetch<Txn[]>(`/transactions${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  });
  return (
    <div>
      <input className="mb-2 w-full rounded border p-2" placeholder="Search merchant…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <table className="w-full text-sm">
        <tbody>
          {data.map((t) => (
            <tr key={t.id} className="border-b">
              <td className="p-2">{t.posted_at.slice(0, 10)}</td>
              <td className="p-2">{t.merchant_raw}</td>
              <td className="p-2 text-right">{t.currency} {t.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Write `frontend/src/transactions/NewTransactionForm.tsx`** and `CsvUpload.tsx`

`NewTransactionForm.tsx`: RHF fields `account_id` (select from accounts query), `posted_at` (`<input type="date">`), `amount`, `merchant_raw`; `POST /transactions`; invalidate `["transactions"]`.

`CsvUpload.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";

export function CsvUpload({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    await fetch(`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/accounts/${accountId}/import`, {
      method: "POST", credentials: "include", body,
    });
    qc.invalidateQueries({ queryKey: ["transactions"] });
  };
  return <input type="file" accept=".csv" onChange={onFile} />;
}
```

- [ ] **Step 5: Write `frontend/src/Dashboard.tsx`** composing the above + a logout button (`POST /auth/logout` → reload).

- [ ] **Step 6: Write `frontend/src/transactions/TransactionList.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { TransactionList } from "./TransactionList";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async () => [{ id: "1", posted_at: "2026-01-01T00:00:00Z", merchant_raw: "Starbucks", amount: "-9.99", currency: "USD" }]),
}));

test("renders a transaction row", async () => {
  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}><TransactionList /></QueryClientProvider>);
  expect(await screen.findByText("Starbucks")).toBeInTheDocument();
});
```

- [ ] **Step 7: Run tests**

Run: `cd frontend && npx vitest run`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: accounts + transactions UI, CSV upload, dashboard"
```

---

### Task 14: Playwright end-to-end smoke + docs + milestone close

**Files:**
- Create: `frontend/e2e/smoke.spec.ts`, `frontend/playwright.config.ts`, `README.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`
- Modify: `frontend/Dockerfile`, `docker-compose.yml` (web service)

**Interfaces:** none (integration + docs).

- [ ] **Step 1: Write `frontend/playwright.config.ts`** pointing `baseURL` to the running web app; assume `docker compose up` provides api + web.

- [ ] **Step 2: Write `frontend/e2e/smoke.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("register → add account → add transaction → see it", async ({ page }) => {
  const email = `u${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password").fill("pw12345");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page).toHaveURL("/");
  await page.getByPlaceholder("Name").fill("Main Checking");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("Main Checking")).toBeVisible();

  // add a transaction via the new-transaction form
  await page.getByPlaceholder("Merchant").fill("Starbucks");
  await page.getByLabel("Amount").fill("-9.99");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await expect(page.getByText("Starbucks")).toBeVisible();
});
```

Note: adjust selectors to match the exact labels/placeholders used in Task 13 forms.

- [ ] **Step 3: Run the smoke test**

Run: `docker compose up -d && cd frontend && npx playwright test`
Expected: PASS. Debug selector mismatches against real forms until green.

- [ ] **Step 4: Write `README.md`** — project intro, quickstart (`cp backend/.env.example backend/.env`, `docker compose up`), links to spec + ARCHITECTURE. Rename note (project working name `openfinance`).

- [ ] **Step 5: Write `docs/ARCHITECTURE.md`** — layering diagram, tenancy model, provider abstraction, encryption, testing strategy. Pull from the M0 spec.

- [ ] **Step 6: Write `CHANGELOG.md`**

```markdown
# Changelog

## [Unreleased] — M0 Foundation
### Added
- Email/password auth with argon2 + server-side sessions.
- Household tenancy; all financial data scoped to household_id.
- BankProvider abstraction with ManualProvider; encrypted provider credentials.
- Accounts, categories, transactions (manual + CSV import) with dedup.
- React frontend: auth, accounts, transactions, CSV upload.
- Postgres + Redis via Docker Compose; Alembic migrations; pytest + vitest + Playwright.
```

- [ ] **Step 7: Full green check** — `cd backend && pytest && ruff check app tests && mypy app` and `cd frontend && npx vitest run && npx tsc --noEmit && npx eslint src`. All PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts README.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "feat: e2e smoke test, README, ARCHITECTURE, CHANGELOG — M0 complete"
```

---

## Self-Review

**Spec coverage:**
- Auth (email+password, sessions, argon2, rate limit) → Tasks 4–6. ✓
- Household tenancy + roles + isolation tests → Tasks 4, 8, 9. ✓
- Provider abstraction + ManualProvider + encrypted creds → Tasks 3, 7. ✓
- Accounts (all types) + categories → Task 8. ✓
- Transactions CRUD/filter/notes + CSV import + dedup → Tasks 9, 10. ✓
- Money as NUMERIC/Decimal, currency column, single-currency enforce → Tasks 8, 9. ✓
- Postgres everywhere, Alembic, Docker Compose → Tasks 1, 4, 11. ✓
- Frontend (auth, accounts, transactions, CSV) → Tasks 12, 13. ✓
- Testing: pytest+testcontainers, vitest, Playwright smoke → Tasks 2, 13, 14. ✓
- Lint/type gates + docs + CHANGELOG → Tasks 11, 14. ✓
- Seams for Plaid/MarketData/LLM/OAuth (declared, not built) → `BankProvider` Task 7; MarketData/LLM protocols noted as declared-only. **Gap:** plan declares `BankProvider` but defers `MarketDataProvider`/`LLMProvider` protocol stubs. Acceptable for M0 — those land in M5/M6; no M0 code depends on them. Left out deliberately (YAGNI).

**Placeholder scan:** No TBD/TODO. Two "adjust selectors to match" notes in Task 14 are integration reality (Playwright selectors bind to real rendered DOM), not placeholders — the forms they bind to are fully specified in Task 13.

**Type consistency:** `household_id: uuid.UUID` threaded consistently through services/deps. `require_household` returns `uuid.UUID` (Task 6) consumed by Tasks 8–10. `apiFetch<T>` generic used consistently frontend. Service names (`create`/`list_for`/`get`/`update`/`delete`) consistent across accounts + transactions.

No blocking issues. Plan ready.
