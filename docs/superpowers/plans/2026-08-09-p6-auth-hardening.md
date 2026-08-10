# P6 Auth Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the auth gaps M0 deliberately deferred — CSRF, session rotation/revoke/idle-timeout, TOTP 2FA, and a shareable-link household invite flow that finally makes `Role.member` reachable and enforceable — without inventing infrastructure a self-hosted, one-household app doesn't need.

**Architecture:** One Alembic revision adds every new column/table the phase needs (`sessions.last_seen_at`, `users.totp_secret`/`totp_enabled`, `household_invites`, `audit_events`). CSRF is an ASGI middleware, not a per-route dependency, so no new mutating endpoint can forget it. TOTP is implemented against stdlib `hmac`/`hashlib`/`base64`/`struct` — no new dependency. Invites are a signed shareable link (no SMTP anywhere in this app). RBAC is one `require_owner` FastAPI dependency, applied at the router level on the four routers that touch sensitive data (documents, connections, tax, export) plus the new invites/audit-log endpoints. Audit log writes are threaded through the handful of sensitive call sites named in the spec, not every mutation.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, `cryptography` (AES-GCM, already used for provider credentials and documents), `slowapi` (existing rate limiter), stdlib `hmac`/`hashlib`/`base64`/`struct`/`secrets`. React 19, TanStack Query, react-hook-form. No new dependencies anywhere.

## Global Constraints

Carried by reference from `docs/superpowers/plans/PLAN-CONSTRAINTS.md` — every task's requirements implicitly include it. The load-bearing ones for this phase:

- Backend gates from `backend/`: `.venv/Scripts/python.exe -m pytest -q`, `.venv/Scripts/python.exe -m ruff check app`, `.venv/Scripts/python.exe -m mypy app`. Frontend gates from `frontend/`: `npm test`, `npm run build` (not `npm run typecheck` — they check different things), `npm run lint`. The real bar is **no new errors in files this phase touches**; `ruff check app` reports 3 and `mypy app` reports 24 pre-existing, none in files this phase touches.
- Every financial/household row carries `household_id`, every service function filters on it. `backend/tests/test_tenancy.py` is service-level, not HTTP-level — new tenancy-sensitive tests follow that shape.
- `backend/tests/conftest.py` provides only `pg_engine` and `db` fixtures, built with `Base.metadata.create_all` — never Alembic. No `household` or `user` fixture exists; tests that need one build it inline, as `test_tenancy.py::_household` does.
- **One Alembic revision for the whole phase.** Everything in Task 1.
- Money is `Decimal`/`NUMERIC(19,4)`/string-in-TS — not touched by this phase, but no task here introduces a float.
- No new dependencies. TOTP is implemented from stdlib per the spec, explicitly checked against this constraint.
- Commit subjects are lowercase and human, no task numbers. Comments explain why, never what.

**Source of truth for scope:** `docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` §2. Read it before touching any task below — this plan does not repeat its reasoning for what's cut (OAuth, passkeys, backup codes, a permissions matrix, `viewer` enforcement, email delivery of invites).

---

## File Structure

**Backend — new:**
- `backend/app/models/household_invite.py` — `HouseholdInvite` model
- `backend/app/models/audit_event.py` — `AuditEvent` model
- `backend/app/services/totp.py` — stdlib RFC 6238 TOTP (no DB, no encryption)
- `backend/app/services/twofa.py` — enrollment, verification, preauth-token issue/resolve (uses `totp.py` + `core/encryption.py`)
- `backend/app/services/invites.py` — invite create/list/revoke/join
- `backend/app/services/audit.py` — `record`/`list_for`
- `backend/app/api/audit.py` — `GET /audit-log`
- `backend/app/schemas/audit.py` — `AuditEventOut`
- `backend/app/core/csrf.py` — the double-submit middleware
- `backend/migrations/versions/d84a2f6c9e17_auth_hardening.py` — the phase's one revision

**Backend — modified:**
- `backend/app/models/session.py` — `+last_seen_at`
- `backend/app/models/user.py` — `+totp_secret`, `+totp_enabled`
- `backend/app/models/__init__.py` — register the two new models
- `backend/app/services/auth.py` — `hash_token` made public, idle timeout in `resolve_session`, `change_password`, session list/revoke
- `backend/app/schemas/auth.py` — `PasswordChange`, `SessionOut`, `TwoFAEnrollOut`, `TwoFACode`, `PreauthCode`, `LoginResult`, `InviteCreateOut`, `InviteOut`, `JoinIn`
- `backend/app/api/deps.py` — `require_owner`
- `backend/app/api/auth.py` — two-step login, password/session/2FA/invite/join endpoints, audit calls
- `backend/app/api/documents.py`, `backend/app/api/connections.py`, `backend/app/api/tax.py`, `backend/app/api/export.py` — owner-gated at the router level; documents/connections also gain audit calls
- `backend/app/main.py` — register `CSRFMiddleware` and the `audit` router

**Frontend — new:**
- `frontend/src/auth/settings.ts` — hooks: sessions, password change, 2FA, invites, audit log
- `frontend/src/pages/SettingsPage.tsx` — account section (all roles) + household section (owner only)
- `frontend/src/pages/JoinPage.tsx` — public `/join/:token`

**Frontend — modified:**
- `frontend/src/api/client.ts` — attach `X-CSRF-Token` on mutating requests
- `frontend/src/auth/AuthPage.tsx` — two-step TOTP login
- `frontend/src/App.tsx` — `/settings`, `/join/:token` routes, `role` on `Me`
- `frontend/src/ui/Shell.tsx` — one `MORE` entry, "Settings"

Each task below is independently testable and ends with a commit. Tasks 1–7 are backend, in dependency order (schema, then the features that read/write it). Tasks 8–9 are frontend. Task 10 is the end-to-end check and docs.

---

### Task 1: Schema — sessions, TOTP columns, invites, audit log

**Files:**
- Create: `backend/app/models/household_invite.py`
- Create: `backend/app/models/audit_event.py`
- Modify: `backend/app/models/session.py`
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/d84a2f6c9e17_auth_hardening.py`
- Test: `backend/tests/test_auth_hardening_schema.py`

**Interfaces:**
- Consumes: `Base`/`UUIDMixin`/`TimestampMixin` from `app.models.base`; `Role` enum from `app.models.user`.
- Produces:
  - `UserSession.last_seen_at: datetime | None`
  - `User.totp_secret: bytes | None`, `User.totp_enabled: bool`
  - `HouseholdInvite` model: `id, household_id, role, token_hash, created_by, expires_at, used_at, created_at`
  - `AuditEvent` model: `id, household_id, user_id, action, event_metadata (dict, DB column "metadata"), created_at`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_hardening_schema.py`:

```python
from datetime import UTC, datetime, timedelta

from app.models.audit_event import AuditEvent
from app.models.household import Household
from app.models.household_invite import HouseholdInvite
from app.models.session import UserSession
from app.models.user import Role
from app.services.auth import register


def test_user_totp_fields_default(db):
    user = register(db, "a@example.com", "pw12345")
    assert user.totp_enabled is False
    assert user.totp_secret is None


def test_session_last_seen_at_is_nullable(db):
    user = register(db, "b@example.com", "pw12345")
    sess = UserSession(
        user_id=user.id, token_hash="x", expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    assert sess.last_seen_at is None


def test_household_invite_round_trip(db):
    h = Household(name="Test")
    db.add(h)
    db.commit()
    db.refresh(h)
    user = register(db, "c@example.com", "pw12345")

    invite = HouseholdInvite(
        household_id=h.id, role=Role.member, token_hash="hash",
        created_by=user.id, expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    assert invite.used_at is None
    assert invite.role == Role.member


def test_audit_event_round_trip(db):
    h = Household(name="Test2")
    db.add(h)
    db.commit()
    db.refresh(h)
    user = register(db, "d@example.com", "pw12345")

    event = AuditEvent(
        household_id=h.id, user_id=user.id, action="session.login",
        event_metadata={"ip": "1.2.3.4"},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    assert event.event_metadata == {"ip": "1.2.3.4"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_hardening_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.household_invite'`

- [ ] **Step 3: Add the TOTP columns**

Modify `backend/app/models/user.py`:

```python
import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


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
    # Envelope-encrypted with app.core.encryption (same AES-GCM scheme as provider
    # credentials and vault documents) — never stored or logged in the clear.
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 4: Add the session idle-timeout column**

Modify `backend/app/models/session.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class UserSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Touched on every resolved request. NULL means "never resolved since issue" —
    # resolve_session falls back to created_at, so a freshly issued session isn't
    # treated as already idle.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 5: Create the two new models**

Create `backend/app/models/household_invite.py`:

```python
"""A shareable-link invite. No email is ever sent — the owner copies the link
themselves. See docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.4
for why: this app has no SMTP anywhere and pitches itself as having no third party
watching your data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.user import Role


class HouseholdInvite(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "household_invites"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    # Every invite this phase issues is Role.member — the column reuses the existing
    # `role` Postgres enum rather than a narrower type, since narrowing it would be a
    # migration of its own the day a second invite role ships.
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Create `backend/app/models/audit_event.py`:

```python
"""Append-only. No service function in app/services/audit.py ever updates or deletes
a row — the only writes are record() and, transitively, whatever the test suite tears
down with the whole table.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AuditEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_events"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    # Python attribute can't be named `metadata` — that's DeclarativeBase's own
    # attribute. The DB column is still named "metadata", matching the spec's table.
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
```

- [ ] **Step 6: Register the new models**

Modify `backend/app/models/__init__.py` — add two lines, alphabetically:

```python
# Import every model module so Base.metadata is complete for create_all / Alembic autogen.
from app.models.account import Account, AccountType  # noqa: F401
from app.models.audit_event import AuditEvent  # noqa: F401
from app.models.budget import Budget  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.category_rule import CategoryRule, MatchType, RuleSource  # noqa: F401
from app.models.connection import ConnStatus, Provider, ProviderConnection  # noqa: F401
from app.models.document import Document, DocumentKind  # noqa: F401
from app.models.goal import Goal, GoalAccount, GoalKind, GoalStatus  # noqa: F401
from app.models.household import Household  # noqa: F401
from app.models.household_invite import HouseholdInvite  # noqa: F401
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus  # noqa: F401
from app.models.security import Security  # noqa: F401
from app.models.security_price import SecurityPrice  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.snapshot import BalanceSnapshot  # noqa: F401
from app.models.trade import Trade, TradeType  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.user import Role, User  # noqa: F401
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_hardening_schema.py -v`
Expected: PASS (4 tests) — `conftest.py` builds the schema with `Base.metadata.create_all`, which now includes the new columns/tables because Step 6 registered them.

- [ ] **Step 8: Write the Alembic revision**

Create `backend/migrations/versions/d84a2f6c9e17_auth_hardening.py`:

```python
"""auth hardening: session idle timeout, TOTP columns, household invites, audit log

Revision ID: d84a2f6c9e17
Revises: b7e4a591c3d0
Create Date: 2026-08-09

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d84a2f6c9e17"
down_revision: Union[str, Sequence[str], None] = "b7e4a591c3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the "role" enum already exists (abd413a14ea9). Reused, not
# recreated — household_invites.role is the same Postgres type as users.role.
role_enum = postgresql.ENUM("owner", "member", "viewer", name="role", create_type=False)


def upgrade() -> None:
    op.add_column("sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_secret", sa.LargeBinary(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "household_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_household_invites_household_id"), "household_invites", ["household_id"]
    )
    op.create_index(
        op.f("ix_household_invites_token_hash"), "household_invites", ["token_hash"], unique=True
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_household_id"), "audit_events", ["household_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_household_id"), table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(op.f("ix_household_invites_token_hash"), table_name="household_invites")
    op.drop_index(op.f("ix_household_invites_household_id"), table_name="household_invites")
    op.drop_table("household_invites")

    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("sessions", "last_seen_at")
    # No enum drop: household_invites.role borrowed the existing "role" type
    # (create_type=False) rather than creating its own, so there is nothing to drop.
```

- [ ] **Step 9: Run the whole-chain migration test**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_migrations.py -v`
Expected: PASS — upgrade to head, downgrade to base, upgrade to head again, all clean.

- [ ] **Step 10: Run ruff and mypy on touched files**

Run: `cd backend && .venv/Scripts/python -m ruff check app/models/user.py app/models/session.py app/models/household_invite.py app/models/audit_event.py app/models/__init__.py`
Run: `.venv/Scripts/python -m mypy app/models/user.py app/models/session.py app/models/household_invite.py app/models/audit_event.py`
Expected: both clean — these are new/small edits to files with no pre-existing errors.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/household_invite.py backend/app/models/audit_event.py backend/app/models/session.py backend/app/models/user.py backend/app/models/__init__.py backend/migrations/versions/d84a2f6c9e17_auth_hardening.py backend/tests/test_auth_hardening_schema.py
git commit -m "feat: schema for session idle timeout, TOTP, invites, and audit log"
```

---

### Task 2: CSRF double-submit middleware

**Files:**
- Create: `backend/app/core/csrf.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_csrf.py`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts` (append)

**Interfaces:**
- Consumes: `settings.local_mode`, `settings.environment` from `app.core.config`.
- Produces: `CSRFMiddleware` (Starlette `BaseHTTPMiddleware`), cookie name `csrf_token`, header name `X-CSRF-Token`.

- [ ] **Step 1: Write the failing backend test**

Create `backend/tests/test_csrf.py`:

```python
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app

app.state.limiter.enabled = False


def client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_get_issues_a_csrf_cookie(db):
    c = client(db)
    r = c.get("/health")
    assert "csrf_token" in r.cookies


def test_mutating_request_without_token_is_rejected(db):
    c = client(db)
    c.get("/health")  # picks up the csrf_token cookie
    r = c.post("/accounts", json={"type": "checking", "name": "X"})
    assert r.status_code == 401 or r.status_code == 403  # unauthenticated is fine too, but never a 500


def test_mutating_request_with_mismatched_token_is_rejected(db, monkeypatch):
    monkeypatch.setattr(settings, "local_mode", False)
    c = client(db)
    c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    c.cookies.set("csrf_token", "real-token")
    r = c.post(
        "/auth/password",
        json={"current_password": "pw12345", "new_password": "newpw123"},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_register_login_join_are_exempt(db):
    c = client(db)
    r = c.post("/auth/register", json={"email": "b@example.com", "password": "pw12345"})
    assert r.status_code == 200  # no X-CSRF-Token header sent, and it still works


def test_csrf_skipped_in_local_mode(db, monkeypatch):
    monkeypatch.setattr(settings, "local_mode", True)
    c = client(db)
    r = c.post("/accounts", json={"type": "checking", "name": "Local"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_csrf.py -v`
Expected: FAIL — every GET/POST call 200s or 401s with no `csrf_token` cookie ever set.

- [ ] **Step 3: Write the middleware**

Create `backend/app/core/csrf.py`:

```python
"""Double-submit CSRF, as an ASGI middleware rather than a per-route Depends — a
route-level dependency can't cleanly see the HTTP method to skip GETs, and a
middleware is one place a new mutating endpoint can't forget to wire up. See
docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.1.

SameSite=Lax on the session cookie already blocks classic cross-site form CSRF; this
closes the gap it leaves (same-site subdomain attacks, older browsers).
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

COOKIE = "csrf_token"
HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# None of these has a session yet to protect — the double-submit pattern has nothing
# to compare a token against until one exists.
EXEMPT_PATHS = {"/auth/register", "/auth/login", "/auth/join", "/auth/2fa/login-verify"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        needs_check = (
            not settings.local_mode
            and request.method not in SAFE_METHODS
            and request.url.path not in EXEMPT_PATHS
        )
        if needs_check:
            cookie_token = request.cookies.get(COOKIE)
            header_token = request.headers.get(HEADER)
            if not cookie_token or not header_token or not secrets.compare_digest(
                cookie_token, header_token
            ):
                return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)

        response = await call_next(request)

        if COOKIE not in request.cookies:
            response.set_cookie(
                COOKIE,
                secrets.token_urlsafe(32),
                httponly=False,  # the frontend must read it to send the header back
                samesite="lax",
                secure=settings.environment != "development",
            )
        return response
```

- [ ] **Step 4: Register the middleware**

Modify `backend/app/main.py` — add the import and one `add_middleware` call, after the CORS middleware (CSRF only needs to run for real requests, not preflight, and `OPTIONS` is already in `SAFE_METHODS` so ordering here doesn't change preflight behavior either way):

```python
from app.api import (
    accounts,
    auth,
    budgets,
    categories,
    category_rules,
    connections,
    documents,
    estate,
    export,
    forecast,
    goals,
    imports,
    insights,
    investments,
    recurring,
    reports,
    tax,
    transactions,
)
from app.api.deps import limiter
from app.core.config import DEFAULT_SECRET_KEY, settings
from app.core.csrf import CSRFMiddleware
from app.core.scheduler import lifespan
```

And, directly below the existing `app.add_middleware(CORSMiddleware, ...)` block:

```python
app.add_middleware(CSRFMiddleware)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_csrf.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full backend suite — this middleware touches every mutating route**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: every existing test that POSTs/PATCHes/DELETEs without an `X-CSRF-Token` header now needs one, OR needs `local_mode` on, OR needs to be an exempt path. Existing tests use `TestClient`, which does **not** send a CSRF header by default. Expect failures here — this step exists to surface them, not to hide them. Fix by making the affected existing test files call `client.get("/health")` once to pick up the cookie, then pass `headers={"X-CSRF-Token": <that cookie value>}` on their mutating calls, e.g. in `test_accounts.py`, `test_budgets_api.py`, `test_goals_api.py`, `test_documents.py`, `test_connections`-adjacent tests, etc. — every test file that exercises a non-GET route while `local_mode` is off. A small shared helper is worth adding at this point:

Create `backend/tests/csrf_helper.py`:

```python
"""Shared by every existing test file that POSTs/PATCHes/DELETEs against a
non-local-mode client, now that CSRFMiddleware protects every mutating route."""

from fastapi.testclient import TestClient


def csrf_client(app, db, get_db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    token = c.get("/health").cookies["csrf_token"]
    c.headers.update({"X-CSRF-Token": token})
    return c
```

Then in each affected test file, replace the ad hoc `TestClient(app)` + `dependency_overrides` setup with `csrf_client(app, db, get_db)`. This is mechanical — every call site that constructs a client for a non-local-mode test needs the header, and the helper is the one place that changes if the cookie/header names ever do.

- [ ] **Step 7: Run the full backend suite again**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: PASS — every test.

- [ ] **Step 8: Write the failing frontend test**

Append to `frontend/src/api/client.test.ts`:

```ts
  it("attaches X-CSRF-Token on a mutating request when the cookie is present", async () => {
    document.cookie = "csrf_token=abc123";
    const spy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/x", { method: "POST", body: "{}" });
    const [, init] = spy.mock.calls[0];
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("does not attach X-CSRF-Token on a GET request", async () => {
    document.cookie = "csrf_token=abc123";
    const spy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/x");
    const [, init] = spy.mock.calls[0];
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });
```

- [ ] **Step 9: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `apiFetch` never reads `document.cookie` today.

- [ ] **Step 10: Wire the header into `apiFetch`**

Modify `frontend/src/api/client.ts`:

```ts
/**
 * Same host the page was served from, port 8000 — so the app works unchanged on
 * localhost, over a LAN address, or across a Tailscale tailnet from a phone.
 * A baked-in "localhost" would make the phone call itself.
 */
const inferred =
  typeof window === "undefined"
    ? "http://localhost:8000"
    : `${window.location.protocol}//${window.location.hostname}:8000`;

export const API_BASE = import.meta.env.VITE_API_URL || inferred;

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie("csrf_token");
    if (token) headers["X-CSRF-Token"] = token;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    credentials: "include",
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // FastAPI errors carry `detail`; slowapi's rate limiter carries `error`.
    const message =
      res.status === 429
        ? "Too many attempts — wait a minute and try again."
        : (body.detail ?? body.error ?? res.statusText);
    throw new Error(message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
```

- [ ] **Step 11: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS — all `client.test.ts` cases, including the pre-existing three.

- [ ] **Step 12: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/core/csrf.py app/main.py && .venv/Scripts/python -m mypy app/core/csrf.py app/main.py`
Run: `cd frontend && npm run build && npm run lint`
Expected: all clean.

- [ ] **Step 13: Commit**

```bash
git add backend/app/core/csrf.py backend/app/main.py backend/tests/test_csrf.py backend/tests/csrf_helper.py frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: double-submit CSRF protection on every mutating route"
```

(If Step 6 touched other existing test files to add the CSRF header, stage and include those too — `git add -u` after reviewing `git status`.)

---

### Task 3: Session hardening — idle timeout, password change, session list/revoke

**Files:**
- Modify: `backend/app/services/auth.py`
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/api/auth.py`
- Test: `backend/tests/test_auth_service.py` (append)
- Test: `backend/tests/test_auth_api.py` (append)

**Interfaces:**
- Consumes: `UserSession.last_seen_at` (Task 1).
- Produces:
  - `auth.hash_token(raw: str) -> str` (renamed from private `_hash_token` — now used cross-module to identify "the current session" among a list)
  - `auth.IDLE_TIMEOUT: timedelta`
  - `auth.WrongPassword` exception
  - `auth.change_password(db, user, current_password, new_password) -> str` (returns a new raw session token)
  - `auth.list_sessions(db, user_id) -> list[UserSession]`
  - `auth.revoke_session(db, user_id, session_id) -> bool`
  - `auth.revoke_other_sessions(db, user_id, keep_token_hash) -> int`

- [ ] **Step 1: Write the failing service tests**

Append to `backend/tests/test_auth_service.py`:

```python
from datetime import UTC, datetime, timedelta

from app.models.session import UserSession


def test_resolve_session_rejects_idle_past_timeout(db):
    user = auth.register(db, "idle@example.com", "pw12345")
    token = auth.issue_session(db, user)
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == auth.hash_token(token)))
    sess.last_seen_at = datetime.now(UTC) - auth.IDLE_TIMEOUT - timedelta(seconds=1)
    db.commit()
    assert auth.resolve_session(db, token) is None


def test_resolve_session_touches_last_seen_at(db):
    user = auth.register(db, "touch@example.com", "pw12345")
    token = auth.issue_session(db, user)
    auth.resolve_session(db, token)
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == auth.hash_token(token)))
    assert sess.last_seen_at is not None


def test_change_password_rotates_and_invalidates_other_sessions(db):
    user = auth.register(db, "rot@example.com", "pw12345")
    old_token = auth.issue_session(db, user)
    new_token = auth.change_password(db, user, "pw12345", "newpassword")
    assert auth.resolve_session(db, old_token) is None
    assert auth.resolve_session(db, new_token) is not None
    assert auth.authenticate(db, "rot@example.com", "newpassword") is not None


def test_change_password_wrong_current_raises(db):
    user = auth.register(db, "wrongpw@example.com", "pw12345")
    with pytest.raises(auth.WrongPassword):
        auth.change_password(db, user, "not-it", "newpassword")


def test_list_and_revoke_sessions(db):
    user = auth.register(db, "multi@example.com", "pw12345")
    t1 = auth.issue_session(db, user)
    t2 = auth.issue_session(db, user)
    sessions = auth.list_sessions(db, user.id)
    assert len(sessions) == 2

    target = next(s for s in sessions if s.token_hash == auth.hash_token(t1))
    assert auth.revoke_session(db, user.id, target.id) is True
    assert auth.resolve_session(db, t1) is None
    assert auth.resolve_session(db, t2) is not None
    # revoking someone else's session id is a no-op, not an error
    other = auth.register(db, "other@example.com", "pw12345")
    other_token = auth.issue_session(db, other)
    other_sess = db.scalar(
        select(UserSession).where(UserSession.token_hash == auth.hash_token(other_token))
    )
    assert auth.revoke_session(db, user.id, other_sess.id) is False


def test_revoke_other_sessions_keeps_the_current_one(db):
    user = auth.register(db, "keep@example.com", "pw12345")
    keep = auth.issue_session(db, user)
    auth.issue_session(db, user)
    auth.issue_session(db, user)
    revoked = auth.revoke_other_sessions(db, user.id, auth.hash_token(keep))
    assert revoked == 2
    assert auth.resolve_session(db, keep) is not None
    assert len(auth.list_sessions(db, user.id)) == 1
```

Add the needed imports at the top of `backend/tests/test_auth_service.py` (the file currently has `import pytest` and `from app.services import auth`; add):

```python
from sqlalchemy import select
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_service.py -v`
Expected: FAIL — `AttributeError: module 'app.services.auth' has no attribute 'hash_token'` (and others).

- [ ] **Step 3: Implement in the service**

Modify `backend/app/services/auth.py`:

```python
import hashlib
import secrets
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


def list_sessions(db: Session, user_id) -> list[UserSession]:
    return list(
        db.scalars(
            select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.created_at.desc())
        )
    )


def revoke_session(db: Session, user_id, session_id) -> bool:
    sess = db.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    )
    if not sess:
        return False
    db.delete(sess)
    db.commit()
    return True


def revoke_other_sessions(db: Session, user_id, keep_token_hash: str) -> int:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_service.py -v`
Expected: PASS — all cases.

- [ ] **Step 5: Add the API-level tests**

Append to `backend/tests/test_auth_api.py` (using the `csrf_client` helper from Task 2):

```python
from tests.csrf_helper import csrf_client


def test_change_password_flow(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "pw@example.com", "password": "pw12345"})
    r = c.post(
        "/auth/password",
        json={"current_password": "pw12345", "new_password": "newpassword"},
    )
    assert r.status_code == 200
    # old cookie session is gone; new one from the response works
    r2 = c.get("/auth/me")
    assert r2.status_code == 200


def test_change_password_wrong_current_rejected(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "pw2@example.com", "password": "pw12345"})
    r = c.post(
        "/auth/password", json={"current_password": "nope", "new_password": "newpassword"}
    )
    assert r.status_code == 401


def test_list_and_revoke_sessions_api(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "sess@example.com", "password": "pw12345"})
    r = c.get("/auth/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True

    r2 = c.delete(f"/auth/sessions/{sessions[0]['id']}")
    assert r2.status_code == 200
    # revoked its own current session — /auth/me now fails
    assert c.get("/auth/me").status_code == 401
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_api.py -v`
Expected: FAIL — `404 Not Found` for `/auth/password` and `/auth/sessions` (routes don't exist yet).

- [ ] **Step 7: Add the schemas**

Modify `backend/app/schemas/auth.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class Credentials(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    household_id: uuid.UUID
    # Lets the client hide login/logout affordances that mean nothing without auth.
    local_mode: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime | None
    is_current: bool


class TwoFAEnrollOut(BaseModel):
    secret: str
    provisioning_uri: str


class TwoFACode(BaseModel):
    code: str


class PreauthCode(BaseModel):
    preauth_token: str
    code: str


class LoginResult(BaseModel):
    status: str  # "ok" | "totp_required"
    user: UserOut | None = None
    preauth_token: str | None = None


class InviteCreateOut(BaseModel):
    id: uuid.UUID
    token: str
    expires_at: datetime


class InviteOut(BaseModel):
    id: uuid.UUID
    role: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    model_config = {"from_attributes": True}


class JoinIn(BaseModel):
    token: str
    email: EmailStr
    password: str
```

- [ ] **Step 8: Add the endpoints**

Modify `backend/app/api/auth.py` — the file grows from 4 routes to a full auth surface. Full replacement:

```python
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
```

(Task 5 and Task 6 each add more routes and imports to this same file — this is the Task 3 baseline.)

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_api.py tests/test_auth_service.py -v`
Expected: PASS — all cases, including the pre-existing ones from before this phase.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: PASS. `auth.hash_token` replaces `auth._hash_token` everywhere it was used internally — confirm no other file imported the private name (`grep -rn "_hash_token" backend/app backend/tests` should show nothing left).

- [ ] **Step 11: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/services/auth.py app/schemas/auth.py app/api/auth.py && .venv/Scripts/python -m mypy app/services/auth.py app/schemas/auth.py app/api/auth.py`
Expected: clean.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/auth.py backend/app/schemas/auth.py backend/app/api/auth.py backend/tests/test_auth_service.py backend/tests/test_auth_api.py
git commit -m "feat: session idle timeout, password change with rotation, session list/revoke"
```

---

### Task 4: TOTP core (stdlib RFC 6238)

**Files:**
- Create: `backend/app/services/totp.py`
- Test: `backend/tests/test_totp.py`

**Interfaces:**
- Produces:
  - `totp.generate_secret() -> str` (base32)
  - `totp.provisioning_uri(secret: str, email: str, issuer: str = "OpenFinance") -> str`
  - `totp.verify_totp(secret: str, code: str, *, at: int | None = None, window: int = 1) -> bool`

No DB, no FastAPI — this is pure stdlib and unit-tested standalone.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_totp.py`:

```python
from app.services.totp import generate_secret, provisioning_uri, verify_totp
from app.services.totp import _hotp  # internal, exercised directly against RFC test vectors


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_totp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.totp'`

- [ ] **Step 3: Implement**

Create `backend/app/services/totp.py`:

```python
"""RFC 6238 TOTP from stdlib only — hmac/hashlib/base64/struct/time/os. The spec
(docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.3) calls this out
explicitly against PLAN-CONSTRAINTS.md's "no new dependencies": pyotp is unnecessary,
this is HMAC-SHA1 over a 30-second counter in under 30 lines.
"""

import base64
import hashlib
import hmac
import os
import struct
import time

_PERIOD_SECONDS = 30
_DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode()


def provisioning_uri(secret: str, email: str, issuer: str = "OpenFinance") -> str:
    return (
        f"otpauth://totp/{issuer}:{email}"
        f"?secret={secret}&issuer={issuer}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD_SECONDS}"
    )


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper())
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    code = truncated % (10**_DIGITS)
    return f"{code:0{_DIGITS}d}"


def verify_totp(secret: str, code: str, *, at: int | None = None, window: int = 1) -> bool:
    """window=1 tolerates one 30s step of clock drift either direction, the
    conventional TOTP allowance."""
    step = (at if at is not None else int(time.time())) // _PERIOD_SECONDS
    return any(
        hmac.compare_digest(_hotp(secret, step + offset), code)
        for offset in range(-window, window + 1)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_totp.py -v`
Expected: PASS — all 6, including the RFC 4226 vectors.

- [ ] **Step 5: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/services/totp.py && .venv/Scripts/python -m mypy app/services/totp.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/totp.py backend/tests/test_totp.py
git commit -m "feat: stdlib TOTP (RFC 6238), no new dependency"
```

---

### Task 5: 2FA enrollment and two-step login

**Files:**
- Create: `backend/app/services/twofa.py`
- Modify: `backend/app/api/auth.py`
- Test: `backend/tests/test_twofa.py`
- Test: `backend/tests/test_auth_api.py` (append)

**Interfaces:**
- Consumes: `totp.generate_secret`/`provisioning_uri`/`verify_totp` from Task 4; `encrypt`/`decrypt` from `app.core.encryption`; `settings.app_secret_key`.
- Produces:
  - `twofa.InvalidPreauth` exception
  - `twofa.start_enrollment(db, user) -> tuple[str, str]` (secret, provisioning_uri)
  - `twofa.confirm_enrollment(db, user, code) -> bool`
  - `twofa.verify_login_code(db, user, code) -> bool`
  - `twofa.issue_preauth(user) -> str`
  - `twofa.resolve_preauth(db, token) -> User`
  - `POST /auth/2fa/enroll`, `POST /auth/2fa/verify`, `POST /auth/2fa/login-verify`
  - `POST /auth/login` now returns `LoginResult` (`status: "ok" | "totp_required"`)

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/test_twofa.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_twofa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.twofa'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/twofa.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_twofa.py -v`
Expected: PASS — all 7.

- [ ] **Step 5: Write the failing API tests**

Append to `backend/tests/test_auth_api.py`:

```python
import time as _time

from app.services.totp import _hotp


def test_2fa_enroll_verify_and_two_step_login(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "flow2fa@example.com", "password": "pw12345"})
    enroll = c.post("/auth/2fa/enroll")
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    code = _hotp(secret, int(_time.time()) // 30)
    verify = c.post("/auth/2fa/verify", json={"code": code})
    assert verify.status_code == 200

    # a fresh (unauthenticated) client now needs two steps to log in
    c2 = csrf_client(app, db, get_db)
    login = c2.post("/auth/login", json={"email": "flow2fa@example.com", "password": "pw12345"})
    assert login.status_code == 200
    body = login.json()
    assert body["status"] == "totp_required"
    assert "session" not in c2.cookies

    login_code = _hotp(secret, int(_time.time()) // 30)
    finish = c2.post(
        "/auth/2fa/login-verify",
        json={"preauth_token": body["preauth_token"], "code": login_code},
    )
    assert finish.status_code == 200
    assert "session" in c2.cookies


def test_login_without_2fa_still_returns_status_ok(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "no2fa@example.com", "password": "pw12345"})
    c2 = csrf_client(app, db, get_db)
    r = c2.post("/auth/login", json={"email": "no2fa@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "session" in c2.cookies
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_api.py -v`
Expected: FAIL — `404` for `/auth/2fa/enroll`, and `test_login_success_and_bad_password` (pre-existing) now fails too, since `login`'s response shape is about to change.

- [ ] **Step 7: Wire the endpoints and the two-step login**

Modify `backend/app/api/auth.py` — replace the `login` function and add three routes. Full file:

```python
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import current_user, limiter
from app.core.config import settings
from app.core.db import get_db
from app.models.user import User
from app.schemas.auth import (
    Credentials,
    LoginResult,
    PasswordChange,
    PreauthCode,
    SessionOut,
    TwoFACode,
    TwoFAEnrollOut,
    UserOut,
)
from app.services import auth, twofa

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


@router.post("/login", response_model=LoginResult)
@limiter.limit("30/minute")
def login(
    body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
) -> LoginResult:
    user = auth.authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.totp_enabled:
        return LoginResult(status="totp_required", preauth_token=twofa.issue_preauth(user))
    _set_cookie(response, auth.issue_session(db, user))
    return LoginResult(status="ok", user=_out(user))


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


@router.post("/2fa/enroll", response_model=TwoFAEnrollOut)
def enroll_2fa(user: User = Depends(current_user), db: Session = Depends(get_db)) -> TwoFAEnrollOut:
    secret, uri = twofa.start_enrollment(db, user)
    return TwoFAEnrollOut(secret=secret, provisioning_uri=uri)


@router.post("/2fa/verify")
@limiter.limit("10/minute")
def verify_2fa(
    body: TwoFACode, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not twofa.confirm_enrollment(db, user, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    return {"status": "ok"}


@router.post("/2fa/login-verify", response_model=UserOut)
@limiter.limit("10/minute")
def login_verify_2fa(
    body: PreauthCode, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    try:
        user = twofa.resolve_preauth(db, body.preauth_token)
    except twofa.InvalidPreauth:
        raise HTTPException(status_code=401, detail="Invalid or expired login")
    if not twofa.verify_login_code(db, user, body.code):
        raise HTTPException(status_code=401, detail="Invalid code")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)
```

- [ ] **Step 8: Fix the pre-existing login test for the new response shape**

Modify `backend/tests/test_auth_api.py` — `test_login_success_and_bad_password` currently asserts on a bare `UserOut`. Update it:

```python
def test_login_success_and_bad_password(db):
    c = client(db)
    c.post("/auth/register", json={"email": "b@example.com", "password": "pw12345"})
    c2 = client(db)
    r = c2.post("/auth/login", json={"email": "b@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "session" in c2.cookies

    r_bad = c2.post("/auth/login", json={"email": "b@example.com", "password": "wrong"})
    assert r_bad.status_code == 401
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_auth_api.py -v`
Expected: PASS — all cases.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 11: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/services/twofa.py app/api/auth.py && .venv/Scripts/python -m mypy app/services/twofa.py app/api/auth.py`
Expected: clean.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/twofa.py backend/app/api/auth.py backend/tests/test_twofa.py backend/tests/test_auth_api.py
git commit -m "feat: TOTP enrollment and a two-step 2FA login"
```

---

### Task 6: Household invites and RBAC

**Files:**
- Create: `backend/app/services/invites.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/api/connections.py`
- Modify: `backend/app/api/tax.py`
- Modify: `backend/app/api/export.py`
- Test: `backend/tests/test_invites.py`
- Test: `backend/tests/test_rbac.py`

**Interfaces:**
- Consumes: `Role` from `app.models.user`; `hash_password`/`EmailTaken` from `app.services.auth`.
- Produces:
  - `invites.InvalidInvite` exception
  - `invites.create_invite(db, household_id, created_by) -> tuple[HouseholdInvite, str]`
  - `invites.list_invites(db, household_id) -> list[HouseholdInvite]`
  - `invites.revoke_invite(db, household_id, invite_id) -> bool`
  - `invites.join(db, token, email, password) -> User`
  - `deps.require_owner(user: User = Depends(current_user)) -> User`
  - `POST /auth/invites`, `GET /auth/invites`, `DELETE /auth/invites/{id}`, `POST /auth/join`

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/test_invites.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from app.models.household_invite import HouseholdInvite
from app.services import auth, invites


def test_create_invite_returns_row_and_raw_token(db):
    owner = auth.register(db, "owner@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    assert invite.token_hash != raw
    assert invite.used_at is None
    assert invite.role.value == "member"


def test_join_places_new_user_in_inviting_household_as_member(db):
    owner = auth.register(db, "owner2@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    joined = invites.join(db, raw, "newmember@example.com", "pw12345")
    assert joined.household_id == owner.household_id
    assert joined.role.value == "member"


def test_join_marks_invite_used(db):
    owner = auth.register(db, "owner3@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw, "newmember2@example.com", "pw12345")
    db.refresh(invite)
    assert invite.used_at is not None


def test_join_rejects_already_used_token(db):
    owner = auth.register(db, "owner4@example.com", "pw12345")
    _, raw = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw, "first@example.com", "pw12345")
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, raw, "second@example.com", "pw12345")


def test_join_rejects_expired_token(db):
    owner = auth.register(db, "owner5@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, raw, "toolate@example.com", "pw12345")


def test_join_rejects_unknown_token(db):
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, "not-a-real-token", "nobody@example.com", "pw12345")


def test_join_still_rejects_taken_email(db):
    owner = auth.register(db, "owner6@example.com", "pw12345")
    auth.register(db, "taken@example.com", "pw12345")
    _, raw = invites.create_invite(db, owner.household_id, owner.id)
    with pytest.raises(auth.EmailTaken):
        invites.join(db, raw, "taken@example.com", "pw12345")


def test_revoke_invite_removes_unused_only(db):
    owner = auth.register(db, "owner7@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    assert invites.revoke_invite(db, owner.household_id, invite.id) is True
    assert db.get(HouseholdInvite, invite.id) is None

    invite2, raw2 = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw2, "used@example.com", "pw12345")
    assert invites.revoke_invite(db, owner.household_id, invite2.id) is False


def test_invites_isolated_by_household(db):
    owner1 = auth.register(db, "iso1@example.com", "pw12345")
    owner2 = auth.register(db, "iso2@example.com", "pw12345")
    invite, _ = invites.create_invite(db, owner1.household_id, owner1.id)
    assert invites.revoke_invite(db, owner2.household_id, invite.id) is False
    assert {i.id for i in invites.list_invites(db, owner1.household_id)} == {invite.id}
    assert invites.list_invites(db, owner2.household_id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_invites.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.invites'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/invites.py`:

```python
"""Shareable-link household invites. See app.models.household_invite for why the
column is Role rather than a narrower type, and the spec §2.4 for why this is a link
the owner copies themselves rather than an email this app has no way to send."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.household_invite import HouseholdInvite
from app.models.user import Role, User
from app.services.auth import EmailTaken, hash_password

INVITE_TTL = timedelta(days=7)


class InvalidInvite(Exception):
    pass


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_invite(
    db: Session, household_id: uuid.UUID, created_by: uuid.UUID
) -> tuple[HouseholdInvite, str]:
    raw = secrets.token_urlsafe(32)
    invite = HouseholdInvite(
        household_id=household_id,
        role=Role.member,
        token_hash=_hash(raw),
        created_by=created_by,
        expires_at=datetime.now(UTC) + INVITE_TTL,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw


def list_invites(db: Session, household_id: uuid.UUID) -> list[HouseholdInvite]:
    return list(
        db.scalars(
            select(HouseholdInvite)
            .where(HouseholdInvite.household_id == household_id)
            .order_by(HouseholdInvite.created_at.desc())
        )
    )


def revoke_invite(db: Session, household_id: uuid.UUID, invite_id: uuid.UUID) -> bool:
    invite = db.scalar(
        select(HouseholdInvite).where(
            HouseholdInvite.id == invite_id, HouseholdInvite.household_id == household_id
        )
    )
    if not invite or invite.used_at is not None:
        return False
    db.delete(invite)
    db.commit()
    return True


def _resolve(db: Session, token: str) -> HouseholdInvite:
    invite = db.scalar(select(HouseholdInvite).where(HouseholdInvite.token_hash == _hash(token)))
    if not invite or invite.used_at is not None or invite.expires_at < datetime.now(UTC):
        raise InvalidInvite()
    return invite


def join(db: Session, token: str, email: str, password: str) -> User:
    invite = _resolve(db, token)
    if db.scalar(select(User).where(User.email == email)):
        raise EmailTaken(email)
    user = User(
        household_id=invite.household_id,
        email=email,
        password_hash=hash_password(password),
        role=invite.role,
    )
    db.add(user)
    invite.used_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_invites.py -v`
Expected: PASS — all 9.

- [ ] **Step 5: Write the failing RBAC tests**

Create `backend/tests/test_rbac.py`:

```python
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False


def _member_client(db, owner_client) -> TestClient:
    invite = owner_client.post("/auth/invites").json()
    c = csrf_client(app, db, get_db)
    c.post(
        "/auth/join",
        json={"token": invite["token"], "email": "member@example.com", "password": "pw12345"},
    )
    return c


def test_owner_can_create_and_list_invites(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own@example.com", "password": "pw12345"})
    r = c.post("/auth/invites")
    assert r.status_code == 200
    assert "token" in r.json()

    r2 = c.get("/auth/invites")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_member_cannot_create_invites(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own2@example.com", "password": "pw12345"})
    member = _member_client(db, c)
    r = member.post("/auth/invites")
    assert r.status_code == 403


def test_member_joins_inviting_household_and_can_reach_household_routes(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own3@example.com", "password": "pw12345"})
    owner_household = c.get("/auth/me").json()["household_id"]
    member = _member_client(db, c)
    me = member.get("/auth/me").json()
    assert me["household_id"] == owner_household
    assert me["role"] == "member"
    # member reads/writes day-to-day data fine
    assert member.get("/accounts").status_code == 200
    assert member.post("/accounts", json={"type": "checking", "name": "Shared"}).status_code == 200


def test_member_blocked_from_owner_only_routes_with_403_not_500(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own4@example.com", "password": "pw12345"})
    member = _member_client(db, c)
    assert member.get("/connections").status_code == 403
    assert member.get("/documents").status_code == 403
    assert member.get("/tax/realized-gains?year=2026").status_code == 403
    assert member.get("/export/all.zip").status_code == 403
    assert member.get("/auth/invites").status_code == 403


def test_owner_reaches_previously_owner_gated_routes(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own5@example.com", "password": "pw12345"})
    assert c.get("/connections").status_code == 200
    assert c.get("/documents").status_code == 200
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac.py -v`
Expected: FAIL — `404` for `/auth/invites` and `/auth/join`; member routes return `401`/`200` instead of `403` since `require_owner` doesn't exist yet.

- [ ] **Step 7: Add `require_owner`**

Modify `backend/app/api/deps.py`:

```python
import secrets
import uuid

from fastapi import Cookie, Depends, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.user import Role, User
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


def require_owner(user: User = Depends(current_user)) -> User:
    """LOCAL_MODE's single user is always Role.owner (auth.register defaults to it),
    so this never adds friction to that path — it only ever bites a real `member`."""
    if user.role != Role.owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return user
```

- [ ] **Step 8: Add the invite/join endpoints**

Modify `backend/app/api/auth.py` — add imports and three routes at the end of the file:

```python
from app.api.deps import current_user, limiter, require_owner
```

(This replaces the existing `from app.api.deps import current_user, limiter` line.)

```python
from app.schemas.auth import (
    Credentials,
    InviteCreateOut,
    InviteOut,
    JoinIn,
    LoginResult,
    PasswordChange,
    PreauthCode,
    SessionOut,
    TwoFACode,
    TwoFAEnrollOut,
    UserOut,
)
from app.services import auth, invites, twofa
```

(Replaces the existing schema-import and `from app.services import auth, twofa` lines.)

And appended at the end of the router:

```python
@router.post("/invites", response_model=InviteCreateOut)
def create_invite(owner: User = Depends(require_owner), db: Session = Depends(get_db)) -> InviteCreateOut:
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    return InviteCreateOut(id=invite.id, token=raw, expires_at=invite.expires_at)


@router.get("/invites", response_model=list[InviteOut])
def list_invites_route(
    owner: User = Depends(require_owner), db: Session = Depends(get_db)
) -> list[InviteOut]:
    return [
        InviteOut(
            id=i.id, role=i.role.value, created_at=i.created_at,
            expires_at=i.expires_at, used_at=i.used_at,
        )
        for i in invites.list_invites(db, owner.household_id)
    ]


@router.delete("/invites/{invite_id}")
def revoke_invite_route(
    invite_id: uuid.UUID, owner: User = Depends(require_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not invites.revoke_invite(db, owner.household_id, invite_id):
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"status": "ok"}


@router.post("/join", response_model=UserOut)
@limiter.limit("10/minute")
def join(
    body: JoinIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    try:
        user = invites.join(db, body.token, body.email, body.password)
    except invites.InvalidInvite:
        raise HTTPException(status_code=400, detail="Invite is invalid, expired, or already used")
    except auth.EmailTaken:
        raise HTTPException(status_code=409, detail="Email already registered")
    _set_cookie(response, auth.issue_session(db, user))
    return _out(user)
```

- [ ] **Step 9: Gate the owner-only routers**

Modify `backend/app/api/documents.py` — change the router line and import:

```python
from app.api.deps import require_household, require_owner
```

```python
router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_owner)])
```

Modify `backend/app/api/connections.py` — same pattern:

```python
from app.api.deps import require_household, require_owner
```

```python
router = APIRouter(prefix="/connections", tags=["connections"], dependencies=[Depends(require_owner)])
```

Modify `backend/app/api/tax.py`:

```python
from app.api.deps import require_household, require_owner
```

```python
router = APIRouter(prefix="/tax", tags=["tax"], dependencies=[Depends(require_owner)])
```

Modify `backend/app/api/export.py`:

```python
from app.api.deps import require_household, require_owner
```

```python
router = APIRouter(prefix="/export", tags=["export"], dependencies=[Depends(require_owner)])
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_rbac.py tests/test_invites.py -v`
Expected: PASS — all cases.

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: PASS. Existing tests for `documents`/`connections`/`tax`/`export` build their client as `owner` by default (registration always creates an owner), so router-level gating should not break any of them — confirm by reading any failures rather than assuming.

- [ ] **Step 12: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/services/invites.py app/api/deps.py app/api/auth.py app/api/documents.py app/api/connections.py app/api/tax.py app/api/export.py`
Run: `.venv/Scripts/python -m mypy app/services/invites.py app/api/deps.py app/api/auth.py app/api/documents.py app/api/connections.py app/api/tax.py app/api/export.py`
Expected: clean.

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/invites.py backend/app/api/deps.py backend/app/api/auth.py backend/app/api/documents.py backend/app/api/connections.py backend/app/api/tax.py backend/app/api/export.py backend/tests/test_invites.py backend/tests/test_rbac.py
git commit -m "feat: shareable-link household invites and owner-gated RBAC"
```

---

### Task 7: Audit log

**Files:**
- Create: `backend/app/services/audit.py`
- Create: `backend/app/schemas/audit.py`
- Create: `backend/app/api/audit.py`
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/api/connections.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Consumes: `AuditEvent` from `app.models.audit_event` (Task 1).
- Produces:
  - `audit.record(db, household_id, user_id, action, metadata=None) -> None`
  - `audit.list_for(db, household_id, since=None, action=None) -> list[AuditEvent]`
  - `GET /audit-log`

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/test_audit.py`:

```python
from datetime import UTC, datetime, timedelta

from app.models.household import Household
from app.services import audit, auth


def _household(db) -> Household:
    h = Household(name="Audit Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def test_record_and_list(db):
    h = _household(db)
    user = auth.register(db, "audit@example.com", "pw12345")
    audit.record(db, h.id, user.id, "session.login", {"ip": "1.2.3.4"})
    events = audit.list_for(db, h.id)
    assert len(events) == 1
    assert events[0].action == "session.login"
    assert events[0].event_metadata == {"ip": "1.2.3.4"}


def test_list_isolated_by_household(db):
    h1, h2 = _household(db), _household(db)
    user = auth.register(db, "audit2@example.com", "pw12345")
    audit.record(db, h1.id, user.id, "session.login")
    audit.record(db, h2.id, user.id, "session.login")
    assert len(audit.list_for(db, h1.id)) == 1
    assert len(audit.list_for(db, h2.id)) == 1


def test_list_filters_by_action_and_since(db):
    h = _household(db)
    user = auth.register(db, "audit3@example.com", "pw12345")
    audit.record(db, h.id, user.id, "session.login")
    audit.record(db, h.id, user.id, "invite.created")

    assert len(audit.list_for(db, h.id, action="invite.created")) == 1
    future = datetime.now(UTC) + timedelta(days=1)
    assert audit.list_for(db, h.id, since=future) == []


def test_metadata_defaults_to_empty_dict(db):
    h = _household(db)
    user = auth.register(db, "audit4@example.com", "pw12345")
    audit.record(db, h.id, user.id, "vault.document_downloaded")
    assert audit.list_for(db, h.id)[0].event_metadata == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.audit'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/audit.py`:

```python
"""Append-only audit trail. record() is called from the small set of sensitive call
sites named in docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.7 —
login, session revoke, invite lifecycle, 2FA enrollment, vault document
download/delete, provider connection add/delete. Not every mutation: a row for every
PATCH /transactions/{id} would be noise, not a trail worth reading.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


def record(
    db: Session,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            household_id=household_id, user_id=user_id, action=action,
            event_metadata=metadata or {},
        )
    )
    db.commit()


def list_for(
    db: Session,
    household_id: uuid.UUID,
    since: datetime | None = None,
    action: str | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.household_id == household_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.created_at >= since)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    return list(db.scalars(stmt.order_by(AuditEvent.created_at.desc())))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_audit.py -v`
Expected: PASS — all 4.

- [ ] **Step 5: Write the failing API test**

Create/extend `backend/tests/test_audit.py` with an API-level case (append):

```python
from tests.csrf_helper import csrf_client
from app.core.db import get_db
from app.main import app

app.state.limiter.enabled = False


def test_audit_log_endpoint_owner_only_and_records_login(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "auditapi@example.com", "password": "pw12345"})

    c2 = csrf_client(app, db, get_db)
    c2.post("/auth/login", json={"email": "auditapi@example.com", "password": "pw12345"})

    r = c.get("/audit-log")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "session.login" in actions
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_audit.py -v`
Expected: FAIL — `404` for `/audit-log`.

- [ ] **Step 7: Add the schema and endpoint**

Create `backend/app/schemas/audit.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    action: str
    event_metadata: dict[str, Any]
    created_at: datetime
    model_config = {"from_attributes": True}
```

Create `backend/app/api/audit.py`:

```python
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_owner
from app.core.db import get_db
from app.models.user import User
from app.schemas.audit import AuditEventOut
from app.services import audit

router = APIRouter(prefix="/audit-log", tags=["audit"], dependencies=[Depends(require_owner)])


@router.get("", response_model=list[AuditEventOut])
def list_audit_log(
    since: datetime | None = None,
    action: str | None = None,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> list[AuditEventOut]:
    return [
        AuditEventOut.model_validate(e) for e in audit.list_for(db, owner.household_id, since=since, action=action)
    ]
```

- [ ] **Step 8: Register the router**

Modify `backend/app/main.py`:

```python
from app.api import (
    accounts,
    audit,
    auth,
    budgets,
    categories,
    category_rules,
    connections,
    documents,
    estate,
    export,
    forecast,
    goals,
    imports,
    insights,
    investments,
    recurring,
    reports,
    tax,
    transactions,
)
```

```python
app.include_router(audit.router)
```

(Add this line alongside the other `app.include_router(...)` calls.)

- [ ] **Step 9: Wire the audit calls at the sensitive call sites**

Modify `backend/app/api/auth.py` — add `from app.services import audit, auth, invites, twofa` (replacing the prior `from app.services import auth, invites, twofa` import) and record at three points:

In `login`, right before `return LoginResult(status="ok", user=_out(user))`:

```python
    audit.record(db, user.household_id, user.id, "session.login")
```

In `login_verify_2fa`, right before the final `return _out(user)`:

```python
    audit.record(db, user.household_id, user.id, "session.login")
```

In `revoke_session`, right before `return {"status": "ok"}`:

```python
    audit.record(db, user.household_id, user.id, "session.revoked", {"session_id": str(session_id)})
```

In `verify_2fa`, right before `return {"status": "ok"}`:

```python
    audit.record(db, user.household_id, user.id, "2fa.enrolled")
```

In `create_invite`, right before `return InviteCreateOut(...)`:

```python
    audit.record(db, owner.household_id, owner.id, "invite.created")
```

In `revoke_invite_route`, right before `return {"status": "ok"}`:

```python
    audit.record(db, owner.household_id, owner.id, "invite.revoked", {"invite_id": str(invite_id)})
```

In `join`, right before the final `return _out(user)`:

```python
    audit.record(db, user.household_id, user.id, "invite.accepted")
```

Modify `backend/app/api/documents.py` — add `from app.services import audit, documents` (replacing `from app.services import documents`), and a `db: Session` + `hid`-based call. `download_document` and `delete_document` need the acting user's id, which `require_household` doesn't carry — switch those two routes to depend on `current_user` instead and derive `hid` from it:

```python
from app.api.deps import current_user
```

(Added alongside the existing `require_household` import — both stay, `list_documents`/`upload_document` keep `require_household`.)

```python
@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    doc = documents.get(db, user.household_id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = documents.read_plaintext(db, user.household_id, document_id)
    except documents.DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    audit.record(db, user.household_id, user.id, "vault.document_downloaded", {"document_id": str(document_id)})
    return Response(
        content=data, media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not documents.delete(db, user.household_id, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    audit.record(db, user.household_id, user.id, "vault.document_deleted", {"document_id": str(document_id)})
    return {"status": "ok"}
```

Add `from app.models.user import User` to `documents.py`'s imports (it currently only imports `Document`/`DocumentKind` from `app.models.document`).

Modify `backend/app/api/connections.py` similarly — `link_simplefin` and `delete_connection` switch to `current_user`:

```python
from app.api.deps import current_user
```

```python
from app.models.user import User
from app.services import audit, connections
```

```python
@router.post("/simplefin", response_model=SyncOut)
def link_simplefin(
    body: SimpleFinLink,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SyncOut:
    """Claim a setup token and immediately pull everything it exposes."""
    try:
        conn = connections.link_simplefin(db, user.household_id, body.setup_token)
        result = connections.sync(db, user.household_id, conn)
    except SimpleFinError as exc:
        log.warning("simplefin link failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(db, user.household_id, user.id, "connection.created", {"provider": conn.provider.value})
    return SyncOut(**result.__dict__, is_demo=_is_demo(conn))


@router.delete("/{connection_id}")
def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not connections.delete(db, user.household_id, connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    audit.record(db, user.household_id, user.id, "connection.deleted", {"connection_id": str(connection_id)})
    return {"status": "ok"}
```

`list_connections` and `sync_connection` keep `require_household` — they aren't in the spec's sensitive-actions list.

- [ ] **Step 10: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: PASS — check `test_documents.py` and any connections tests still pass now that two routes changed their dependency from `require_household` to `current_user` (both still resolve `household_id`, just via a different path — behavior for a valid session is unchanged).

- [ ] **Step 12: Gates**

Run: `cd backend && .venv/Scripts/python -m ruff check app/services/audit.py app/schemas/audit.py app/api/audit.py app/api/auth.py app/api/documents.py app/api/connections.py app/main.py`
Run: `.venv/Scripts/python -m mypy app/services/audit.py app/schemas/audit.py app/api/audit.py app/api/auth.py app/api/documents.py app/api/connections.py app/main.py`
Expected: clean.

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/audit.py backend/app/schemas/audit.py backend/app/api/audit.py backend/app/api/auth.py backend/app/api/documents.py backend/app/api/connections.py backend/app/main.py backend/tests/test_audit.py
git commit -m "feat: append-only audit log for sensitive account and vault actions"
```

---

### Task 8: Frontend — account settings (sessions, password, 2FA) and two-step login

**Files:**
- Create: `frontend/src/auth/settings.ts`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/auth/AuthPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/ui/Shell.tsx`
- Test: `frontend/src/auth/settings.test.ts`

**Interfaces:**
- Consumes: `apiFetch` from `../api/client`.
- Produces: `useSessions`, `useRevokeSession`, `useRevokeOtherSessions`, `useChangePassword`, `useEnroll2FA`, `useVerify2FA` hooks; `SettingsPage` (account section — household section arrives in Task 9); two-step TOTP prompt inside `AuthPage`.

- [ ] **Step 1: Write the failing hook test**

Create `frontend/src/auth/settings.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { useSessions, useChangePassword } from "./settings";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useSessions", () => {
  it("fetches the session list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify([{ id: "1", is_current: true }]), { status: 200 })),
    );
    const { result } = renderHook(() => useSessions(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe("useChangePassword", () => {
  it("posts current and new password", async () => {
    const spy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", spy);
    const { result } = renderHook(() => useChangePassword(), { wrapper });
    await result.current.mutateAsync({ current_password: "a", new_password: "b" });
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/auth/password");
    expect(init?.method).toBe("POST");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `frontend/src/auth/settings.ts` doesn't exist.

- [ ] **Step 3: Write the hooks**

Create `frontend/src/auth/settings.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

export type Session = {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  is_current: boolean;
};

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: () => apiFetch<Session[]>("/auth/sessions") });
}

export function useRevokeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useRevokeOtherSessions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/auth/sessions", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiFetch("/auth/password", { method: "POST", body: JSON.stringify(body) }),
  });
}

export type Enrollment = { secret: string; provisioning_uri: string };

export function useEnroll2FA() {
  return useMutation({
    mutationFn: () => apiFetch<Enrollment>("/auth/2fa/enroll", { method: "POST" }),
  });
}

export function useVerify2FA() {
  return useMutation({
    mutationFn: (code: string) =>
      apiFetch("/auth/2fa/verify", { method: "POST", body: JSON.stringify({ code }) }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Two-step login in `AuthPage`**

Modify `frontend/src/auth/AuthPage.tsx` — the login path now returns `{status, preauth_token?}` instead of a bare user, so a second code field appears when needed. Full file:

```tsx
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Form = { email: string; password: string };
type CodeForm = { code: string };

// ponytail: one component for both modes — the pages differ only in copy + endpoint.
const MODES = {
  register: {
    title: "Create account",
    cta: "Sign up",
    path: "/auth/register",
    alt: "/login",
    altText: "Have an account? Log in",
  },
  login: {
    title: "Welcome back",
    cta: "Log in",
    path: "/auth/login",
    alt: "/register",
    altText: "Need an account? Sign up",
  },
} as const;

export function AuthPage({ mode }: { mode: keyof typeof MODES }) {
  const m = MODES[mode];
  const nav = useNavigate();
  const qc = useQueryClient();
  const [preauthToken, setPreauthToken] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>();
  const {
    register: registerCode,
    handleSubmit: handleCodeSubmit,
    setError: setCodeError,
    formState: { errors: codeErrors, isSubmitting: codeSubmitting },
  } = useForm<CodeForm>();

  const onSubmit = async (data: Form) => {
    try {
      if (mode === "register") {
        await apiFetch(m.path, { method: "POST", body: JSON.stringify(data) });
        await qc.invalidateQueries({ queryKey: ["me"] });
        nav("/");
        return;
      }
      const result = await apiFetch<{ status: string; preauth_token?: string }>(m.path, {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (result.status === "totp_required" && result.preauth_token) {
        setPreauthToken(result.preauth_token);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  const onCodeSubmit = async (data: CodeForm) => {
    try {
      await apiFetch("/auth/2fa/login-verify", {
        method: "POST",
        body: JSON.stringify({ preauth_token: preauthToken, code: data.code }),
      });
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setCodeError("root", { message: (e as Error).message });
    }
  };

  if (preauthToken) {
    return (
      <div className="grid min-h-screen place-items-center p-6">
        <form onSubmit={handleCodeSubmit(onCodeSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
          <h1 className="font-display text-4xl">Enter your code</h1>
          <p className="text-sm text-muted">Open your authenticator app and enter the 6-digit code.</p>
          <label className="flex flex-col gap-1.5">
            <span className="label">Code</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              {...registerCode("code", { required: "Code is required" })}
            />
          </label>
          {codeErrors.code && <span className="text-sm text-clay">{codeErrors.code.message}</span>}
          {codeErrors.root && (
            <span className="rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
              {codeErrors.root.message}
            </span>
          )}
          <button disabled={codeSubmitting} className="btn mt-1 w-full">
            {codeSubmitting ? "…" : "Verify"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between border-r border-line p-12 lg:flex">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl leading-none text-acid">O</span>
          <span className="text-sm font-medium tracking-[0.2em] uppercase">Finance</span>
        </div>
        <div>
          <p className="font-display text-5xl leading-[1.05] text-balance">
            Every account, every transaction, <em className="text-acid">in one place.</em>
          </p>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-muted">
            Self-hosted. Your data lives in your database, on your machine — no third party
            watching your spending.
          </p>
        </div>
        <p className="label">Household finance · self-hosted</p>
      </aside>

      <main className="flex items-center justify-center p-6">
        <form onSubmit={handleSubmit(onSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
          <h1 className="font-display text-4xl">{m.title}</h1>

          <label className="flex flex-col gap-1.5">
            <span className="label">Email</span>
            <input
              type="email"
              placeholder="Email"
              autoComplete="email"
              {...register("email", { required: "Email is required" })}
            />
          </label>
          {errors.email && <span className="text-sm text-clay">{errors.email.message}</span>}

          <label className="flex flex-col gap-1.5">
            <span className="label">Password</span>
            <input
              type="password"
              placeholder="Password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              {...register("password", {
                required: "Password is required",
                minLength: { value: 6, message: "At least 6 characters" },
              })}
            />
          </label>
          {errors.password && <span className="text-sm text-clay">{errors.password.message}</span>}
          {errors.root && (
            <span className="rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
              {errors.root.message}
            </span>
          )}

          <button disabled={isSubmitting} className="btn mt-1 w-full">
            {isSubmitting ? "…" : m.cta}
          </button>

          <Link
            to={m.alt}
            className="btn-ghost w-full text-center transition-colors hover:text-acid"
          >
            {m.altText}
          </Link>
        </form>
      </main>
    </div>
  );
}
```

- [ ] **Step 6: The account section of `SettingsPage`**

Create `frontend/src/pages/SettingsPage.tsx`:

```tsx
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { PageHead, Card, Empty } from "../ui/Shell";
import {
  useSessions,
  useRevokeSession,
  useRevokeOtherSessions,
  useChangePassword,
  useEnroll2FA,
  useVerify2FA,
} from "../auth/settings";

type Me = { role: string };
type PasswordForm = { current_password: string; new_password: string };
type CodeForm = { code: string };

function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/auth/me") });
}

function SessionsCard() {
  const { data: sessions } = useSessions();
  const revoke = useRevokeSession();
  const revokeOthers = useRevokeOtherSessions();

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Sessions</h2>
      {!sessions?.length ? (
        <Empty>No active sessions.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between text-sm">
              <span>
                {s.is_current ? "This device" : "Other device"} · signed in{" "}
                {new Date(s.created_at).toLocaleDateString()}
              </span>
              {!s.is_current && (
                <button className="btn-ghost text-clay" onClick={() => revoke.mutate(s.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <button className="btn-ghost mt-3 text-sm" onClick={() => revokeOthers.mutate()}>
        Log out other devices
      </button>
    </Card>
  );
}

function PasswordCard() {
  const change = useChangePassword();
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } =
    useForm<PasswordForm>();

  const onSubmit = async (data: PasswordForm) => {
    try {
      await change.mutateAsync(data);
      reset();
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Password</h2>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
        <input
          type="password"
          placeholder="Current password"
          {...register("current_password", { required: true })}
        />
        <input
          type="password"
          placeholder="New password"
          {...register("new_password", { required: true, minLength: 6 })}
        />
        {errors.root && <span className="text-sm text-clay">{errors.root.message}</span>}
        <button disabled={isSubmitting} className="btn w-fit">
          {isSubmitting ? "…" : "Change password"}
        </button>
      </form>
    </Card>
  );
}

function TwoFACard() {
  const enroll = useEnroll2FA();
  const verify = useVerify2FA();
  const [enrolled, setEnrolled] = useState(false);
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<CodeForm>();

  const onVerify = async (data: CodeForm) => {
    try {
      await verify.mutateAsync(data.code);
      setEnrolled(true);
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Two-factor authentication</h2>
      {enrolled ? (
        <p className="text-sm text-acid">2FA is enabled on your account.</p>
      ) : enroll.data ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">
            Add this to your authenticator app, then enter a code to confirm:
          </p>
          <code className="break-all rounded-lg border border-line bg-[rgba(237,234,228,0.04)] p-2 text-xs">
            {enroll.data.provisioning_uri}
          </code>
          <form onSubmit={handleSubmit(onVerify)} className="flex gap-2">
            <input
              inputMode="numeric"
              placeholder="000000"
              className="flex-1"
              {...register("code", { required: true })}
            />
            <button disabled={isSubmitting} className="btn">
              {isSubmitting ? "…" : "Confirm"}
            </button>
          </form>
          {errors.root && <span className="text-sm text-clay">{errors.root.message}</span>}
        </div>
      ) : (
        <button className="btn w-fit" onClick={() => enroll.mutate()}>
          Enable 2FA
        </button>
      )}
    </Card>
  );
}

export function SettingsPage() {
  const { data: me } = useMe();

  return (
    <>
      <PageHead title="Settings" sub="Your account, sessions, and security" />
      <div className="flex flex-col gap-5">
        <SessionsCard />
        <PasswordCard />
        <TwoFACard />
      </div>
      {/* Household section (invites, audit log) — owner only, added in the next task. */}
      {me?.role === "owner" && null}
    </>
  );
}
```

- [ ] **Step 7: Wire the route and nav entry**

Modify `frontend/src/App.tsx` — add the import, the `role` field on `Me`, and the route:

```tsx
import { SettingsPage } from "./pages/SettingsPage";
```

```tsx
type Me = { email: string; household_id: string; local_mode: boolean; role: string };
```

```tsx
          <Route
            path="/settings"
            element={
              <Protected>
                <SettingsPage />
              </Protected>
            }
          />
```

(Placed alongside the other `<Protected>` routes, before the catch-all `*` route.)

Modify `frontend/src/ui/Shell.tsx` — add one entry to `MORE`:

```tsx
export const MORE = [
  { to: "/investments", label: "Investments", short: "Invest", end: false, glyph: "◈" },
  { to: "/recurring", label: "Recurring", short: "Bills", end: false, glyph: "↻" },
  { to: "/budgets", label: "Budgets", short: "Budgets", end: false, glyph: "▥" },
  { to: "/goals", label: "Goals", short: "Goals", end: false, glyph: "◎" },
  { to: "/reports", label: "Reports", short: "Reports", end: false, glyph: "▦" },
  { to: "/settings", label: "Settings", short: "Settings", end: false, glyph: "⚙" },
];
```

- [ ] **Step 8: Run the frontend suite**

Run: `cd frontend && npm test`
Expected: PASS — all files, including `AuthPage`'s implicit coverage via any existing render tests and the new `settings.test.ts`.

- [ ] **Step 9: Gates**

Run: `cd frontend && npm run build && npm run lint`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/auth/settings.ts frontend/src/auth/settings.test.ts frontend/src/auth/AuthPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/App.tsx frontend/src/ui/Shell.tsx
git commit -m "feat: account settings — sessions, password change, 2FA, two-step login"
```

---

### Task 9: Frontend — invites, join page, audit log, and role-gated nav

**Files:**
- Modify: `frontend/src/auth/settings.ts`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Create: `frontend/src/pages/JoinPage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/auth/settings.test.ts` (append)

**Interfaces:**
- Consumes: hooks from Task 8.
- Produces: `useInvites`, `useCreateInvite`, `useRevokeInvite`, `useAuditLog` hooks; the household section of `SettingsPage`; `JoinPage` at `/join/:token`.

- [ ] **Step 1: Write the failing hook test**

Append to `frontend/src/auth/settings.test.ts`:

```ts
import { useCreateInvite, useAuditLog } from "./settings";

describe("useCreateInvite", () => {
  it("posts to /auth/invites", async () => {
    const spy = vi.fn(
      async () =>
        new Response(JSON.stringify({ id: "1", token: "raw-token", expires_at: "2026-08-16" }), {
          status: 200,
        }),
    );
    vi.stubGlobal("fetch", spy);
    const { result } = renderHook(() => useCreateInvite(), { wrapper });
    const invite = await result.current.mutateAsync();
    expect(invite.token).toBe("raw-token");
  });
});

describe("useAuditLog", () => {
  it("fetches the audit log", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify([{ id: "1", action: "session.login" }]), { status: 200 })),
    );
    const { result } = renderHook(() => useAuditLog(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].action).toBe("session.login");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `useCreateInvite`/`useAuditLog` don't exist.

- [ ] **Step 3: Add the hooks**

Modify `frontend/src/auth/settings.ts` — append:

```ts
export type Invite = {
  id: string;
  role: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
};

export function useInvites() {
  return useQuery({ queryKey: ["invites"], queryFn: () => apiFetch<Invite[]>("/auth/invites") });
}

export function useCreateInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ id: string; token: string; expires_at: string }>("/auth/invites", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/auth/invites/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}

export type AuditEvent = {
  id: string;
  user_id: string;
  action: string;
  event_metadata: Record<string, unknown>;
  created_at: string;
};

export function useAuditLog() {
  return useQuery({ queryKey: ["audit-log"], queryFn: () => apiFetch<AuditEvent[]>("/audit-log") });
}

export function useJoinHousehold() {
  return useMutation({
    mutationFn: (body: { token: string; email: string; password: string }) =>
      apiFetch("/auth/join", { method: "POST", body: JSON.stringify(body) }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: The household section of `SettingsPage`**

Modify `frontend/src/pages/SettingsPage.tsx` — add two cards and render them for owners only. Add these imports:

```tsx
import { useInvites, useCreateInvite, useRevokeInvite, useAuditLog } from "../auth/settings";
```

Add two components above `SettingsPage`:

```tsx
function InvitesCard() {
  const { data: invites } = useInvites();
  const create = useCreateInvite();
  const revoke = useRevokeInvite();
  const [link, setLink] = useState<string | null>(null);

  const onCreate = async () => {
    const invite = await create.mutateAsync();
    setLink(`${window.location.origin}/join/${invite.token}`);
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Household invites</h2>
      <p className="mb-3 text-sm text-muted">
        Share a link to add another member — no email is sent, you send it yourself.
      </p>
      {link && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-line p-2 text-xs">
          <code className="flex-1 break-all">{link}</code>
          <button className="btn-ghost" onClick={() => navigator.clipboard.writeText(link)}>
            Copy
          </button>
        </div>
      )}
      <button className="btn mb-4 w-fit" onClick={onCreate}>
        Generate invite link
      </button>
      {!invites?.length ? (
        <Empty>No pending invites.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {invites.map((i) => (
            <li key={i.id} className="flex items-center justify-between text-sm">
              <span>
                {i.used_at ? "Used" : `Expires ${new Date(i.expires_at).toLocaleDateString()}`}
              </span>
              {!i.used_at && (
                <button className="btn-ghost text-clay" onClick={() => revoke.mutate(i.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AuditLogCard() {
  const { data: events } = useAuditLog();
  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Audit log</h2>
      {!events?.length ? (
        <Empty>No events recorded yet.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {events.map((e) => (
            <li key={e.id} className="flex items-center justify-between text-sm">
              <span>{e.action}</span>
              <span className="text-muted">{new Date(e.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
```

Replace the placeholder line at the bottom of `SettingsPage`:

```tsx
      {me?.role === "owner" && null}
```

with:

```tsx
      {me?.role === "owner" && (
        <div className="mt-5 flex flex-col gap-5">
          <InvitesCard />
          <AuditLogCard />
        </div>
      )}
```

- [ ] **Step 6: The public join page**

Create `frontend/src/pages/JoinPage.tsx`:

```tsx
import { useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useJoinHousehold } from "../auth/settings";

type Form = { email: string; password: string };

export function JoinPage() {
  const { token } = useParams<{ token: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const join = useJoinHousehold();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const onSubmit = async (data: Form) => {
    if (!token) return;
    try {
      await join.mutateAsync({ token, ...data });
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <form onSubmit={handleSubmit(onSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
        <h1 className="font-display text-4xl">Join household</h1>
        <p className="text-sm text-muted">You've been invited to join a shared household.</p>

        <label className="flex flex-col gap-1.5">
          <span className="label">Email</span>
          <input type="email" autoComplete="email" {...register("email", { required: "Email is required" })} />
        </label>
        {errors.email && <span className="text-sm text-clay">{errors.email.message}</span>}

        <label className="flex flex-col gap-1.5">
          <span className="label">Password</span>
          <input
            type="password"
            autoComplete="new-password"
            {...register("password", {
              required: "Password is required",
              minLength: { value: 6, message: "At least 6 characters" },
            })}
          />
        </label>
        {errors.password && <span className="text-sm text-clay">{errors.password.message}</span>}
        {errors.root && (
          <span className="rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
            {errors.root.message}
          </span>
        )}

        <button disabled={isSubmitting} className="btn mt-1 w-full">
          {isSubmitting ? "…" : "Join"}
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 7: Wire the public route**

Modify `frontend/src/App.tsx`:

```tsx
import { JoinPage } from "./pages/JoinPage";
```

```tsx
          <Route path="/join/:token" element={<JoinPage />} />
```

(Placed alongside `/login` and `/register` — outside `<Protected>`, since joining happens before a session exists.)

- [ ] **Step 8: Run the frontend suite**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 9: Gates**

Run: `cd frontend && npm run build && npm run lint`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/auth/settings.ts frontend/src/auth/settings.test.ts frontend/src/pages/SettingsPage.tsx frontend/src/pages/JoinPage.tsx frontend/src/App.tsx
git commit -m "feat: household invites, join page, and the owner-only audit log view"
```

---

### Task 10: End-to-end check and docs

**Files:**
- Create: `frontend/e2e/invites.spec.ts`
- Modify: `TASK.md`

**Interfaces:**
- Consumes: the full stack from Tasks 1–9.
- Produces: one Playwright spec covering register → generate invite → join in a second browser context → member sees a 403 on an owner-only page action.

- [ ] **Step 1: Check the existing e2e setup**

Run: `cd frontend && cat playwright.config.ts` (or open it) to confirm the base URL and how `smoke.spec.ts` starts a session, so the new spec matches the existing pattern rather than inventing a second one.

- [ ] **Step 2: Write the e2e spec**

Create `frontend/e2e/invites.spec.ts` (mirror whatever pattern `frontend/e2e/smoke.spec.ts` uses for registering a fresh user — the exact API depends on that file's existing helpers; the shape below is the scenario, not a prescription of Playwright fixture names your codebase may already have):

```ts
import { test, expect } from "@playwright/test";

test("owner invites a member, who joins and is blocked from an owner-only page", async ({ browser }) => {
  const ownerEmail = `owner-${Date.now()}@example.com`;
  const memberEmail = `member-${Date.now()}@example.com`;

  const ownerContext = await browser.newContext();
  const ownerPage = await ownerContext.newPage();
  await ownerPage.goto("/register");
  await ownerPage.getByPlaceholder("Email").fill(ownerEmail);
  await ownerPage.getByPlaceholder("Password").fill("pw123456");
  await ownerPage.getByRole("button", { name: "Sign up" }).click();
  await expect(ownerPage).toHaveURL("/");

  await ownerPage.goto("/settings");
  await ownerPage.getByRole("button", { name: "Generate invite link" }).click();
  const link = await ownerPage.locator("code").first().innerText();

  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  await memberPage.goto(new URL(link).pathname);
  await memberPage.getByPlaceholder("Email", { exact: false }).first().fill(memberEmail);
  await memberPage.locator('input[type="password"]').fill("pw123456");
  await memberPage.getByRole("button", { name: "Join" }).click();
  await expect(memberPage).toHaveURL("/");

  // Member has no owner-only nav entry to the vault/connections; hitting the API
  // directly confirms the server-side gate, independent of what the UI renders.
  const response = await memberPage.request.get("/connections", { failOnStatusCode: false });
  expect(response.status()).toBe(403);

  await ownerContext.close();
  await memberContext.close();
});
```

- [ ] **Step 3: Run the e2e suite**

Run: `cd frontend && docker compose up -d && npm run dev` (in one terminal), then `npm run e2e` (in another).
Expected: `smoke.spec.ts` and `categorization.spec.ts` still pass; `mobile.spec.ts` still fails for its pre-existing, unrelated reason (`AccountsPage.tsx` heading strict-mode violation — not this phase's regression, per `PLAN-CONSTRAINTS.md`); `invites.spec.ts` passes. If the actual button/label text your `AuthPage`/`JoinPage`/`SettingsPage` render differs slightly from what's guessed above, adjust the locators to match what Task 8/9 actually shipped — don't change the app to match the test.

- [ ] **Step 4: Update `TASK.md`**

Modify `TASK.md` — the Phase status table row for P6 and the "Starting P6" section. Replace:

```markdown
| **P6** | Auth hardening — CSRF, session rotation/revoke, TOTP 2FA, RBAC enforcement, audit log | not yet written | **Starting now.** Independent of P7/P8. |
```

with:

```markdown
| P6 | Auth hardening — CSRF, session rotation/revoke, TOTP 2FA, RBAC enforcement, audit log | `docs/superpowers/plans/2026-08-09-p6-auth-hardening.md` | **Shipped, merged to `main`.** |
```

And replace the `## Starting P6` section with:

```markdown
## Starting P7

P6 is done: CSRF double-submit, session idle timeout + rotation on password change,
session list/revoke, TOTP 2FA with a two-step login, shareable-link household
invites, and owner-gated RBAC on connections/documents/tax/export/invites/audit-log.
`Role.member` is reachable and enforced for the first time.

Read `docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` §3 before
writing the P7 implementation plan. Independent of P6/P8 — no data-model dependency.
```

- [ ] **Step 5: Full gate run, all seven commands**

Run, from `backend/`:
```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check app tests
.venv/Scripts/python -m mypy app
```
Expected: pytest all green; ruff/mypy at or below the pre-existing baseline (174/24 as of the last TASK.md update) — this phase's files contribute zero new errors, but the pre-existing count in files this phase didn't touch is not this phase's job to fix.

Run, from `frontend/`:
```bash
npm test
npm run build
npm run lint
npm run e2e
```
Expected: `npm test` all green; `npm run build` clean (not just `npm run typecheck` — see `PLAN-CONSTRAINTS.md`); `npm run lint` clean; `npm run e2e` — `smoke.spec.ts`, `categorization.spec.ts`, `invites.spec.ts` pass, `mobile.spec.ts` fails for its documented pre-existing reason.

Paste all seven outputs before claiming the phase done — do not assert it.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/invites.spec.ts TASK.md
git commit -m "docs: P6 ships — CSRF, session hardening, 2FA, invites, RBAC, audit log"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` §2):
- §2.1 CSRF double-submit → Task 2.
- §2.2 Session rotation, list/revoke, idle+absolute timeout → Task 3.
- §2.3 TOTP 2FA, envelope-encrypted secret, two-step login → Tasks 4–5.
- §2.4 Invites (shareable link, not email), RBAC (`require_owner`, `member` reachable, `viewer` left unassigned) → Task 6.
- §2.5/§2.6 OAuth/passkeys — confirmed cut, no task references them.
- §2.7 Audit log, append-only, the named sensitive call sites, owner-only `GET /audit-log` → Task 7.
- Spec's test list (CSRF rejected/exempt/local-mode-skipped, rotation invalidates old token, idle timeout, TOTP round trip + rate-limited wrong code, invite expired/used rejected, member lands in inviting household and gets 403 not 500, no plaintext secrets in audit) → covered across Tasks 2, 3, 5, 6, 7's test files.
- Backup codes, permissions matrix, per-field diffing, `viewer` enforcement, email delivery — confirmed cut, no task builds them.

**Placeholder scan:** no task step describes what to do without showing the code; every test file has real assertions; no `TBD`/"add error handling"/"similar to Task N" language.

**Type/name consistency checked:** `auth.hash_token` (renamed from `_hash_token` in Task 3) is used consistently by name in Tasks 3, 5's `test_preauth_token` tests (via `twofa`, which doesn't call it), and Task 6/7's test helpers. `require_owner` (Task 6) is imported identically in Tasks 6 and 7. `AuditEvent.event_metadata` (DB column `"metadata"`) is named identically in the model (Task 1), service (Task 7), and schema (Task 7) — no `metadata`/`event_metadata` mismatch anywhere. `LoginResult.status` values (`"ok"` / `"totp_required"`) match between Task 5's backend and Task 8's frontend `AuthPage`. Frontend `Session`/`Invite`/`AuditEvent` TS types (Task 8/9) match their `SessionOut`/`InviteOut`/`AuditEventOut` Pydantic counterparts field-for-field.
