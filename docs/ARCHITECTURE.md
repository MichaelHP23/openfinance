# Architecture

## Layering

```
api/       routers only — parse, authorize via deps, delegate. No ORM queries, no business rules.
services/  business logic, transactions, tenancy enforcement.
providers/ BankProvider protocol + implementations (ManualProvider today, Plaid later).
models/    SQLAlchemy 2.x declarative models.
core/      config, db session, security (argon2), encryption (AES-GCM).
```

Dependencies point one way: `api → services → (providers + models) → core`.

## Tenancy

A `Household` owns everything financial. `User` belongs to one household with a role
(`owner` / `member` / `viewer`). Every financial table carries a non-null `household_id`,
and every service function takes `household_id` as an argument and filters on it — reads
and writes both. `require_household` derives it from the session cookie, so a router can
never accidentally hand a service the wrong one.

Cross-household reads return `None`/404 rather than raising, so the caller can't
distinguish "not yours" from "doesn't exist". Isolation is covered by
`tests/test_tenancy.py` and the tenancy cases in `tests/test_transactions.py`.

## Auth

`LOCAL_MODE` short-circuits `current_user` to one auto-created local household, so a
single-user desktop install has no login. It is refused unless
`ENVIRONMENT=development`, because it removes authentication entirely. Everything below
describes the hosted path (`LOCAL_MODE=false`), which stays fully wired either way.

- Passwords: argon2id via `argon2-cffi`.
- Sessions: opaque `secrets.token_urlsafe(32)` in an httpOnly, SameSite=Lax cookie;
  only `sha256(token)` is stored, with a 30-day expiry checked on every resolve.
- Rate limits: slowapi (Redis-backed) on register/login.
- CORS: credentialed, restricted to exact origins from `CORS_ORIGINS`. Never a wildcard.

CSRF: SameSite=Lax is the M0 mitigation; double-submit tokens are deferred to M10.

## Provider abstraction

`BankProvider` is a `Protocol` — `link_account`, `fetch_accounts`, `fetch_transactions`
over `AccountDTO` / `TxnDTO`. Providers return DTOs, never ORM objects, so a new
integration can't leak its shape into the domain. `ManualProvider` and `SimpleFinProvider`
both implement it; Plaid would too, without touching a service.

`services/sync.py` is provider-agnostic: it takes anything satisfying the protocol,
matches provider accounts to local rows on `accounts.external_id`, and skips transactions
whose `(account_id, external_id)` it already holds. Tests drive it with a `FakeProvider`,
so sync logic is verified without a network. `SimpleFinProvider` itself is tested against
`httpx.MockTransport`, covering claim failures, reused tokens, partial institution
outages, non-JSON bodies, and non-numeric balances.

Credentials use envelope encryption: a random 32-byte DEK per blob, wrapped by a KEK
derived from `APP_SECRET_KEY`, both AES-256-GCM. The AAD binds ciphertext to
`household_id:provider`, so a blob copied between rows fails to decrypt instead of
silently decrypting under the wrong context.

## Money

`NUMERIC(19,4)` in Postgres, `Decimal` in Python, never float. Signed amounts: negative is
outflow, positive is inflow. `currency` is `char(3)` on accounts and transactions; v1
enforces USD in the service layer, so multi-currency is a service change and not a migration.

## Testing

- Backend: pytest against a real Postgres (testcontainers), one container per session,
  each test in a rolled-back transaction. No SQLite — the app uses Postgres types.
- Frontend: vitest + Testing Library for units.
- End-to-end: Playwright drives register → account → transaction → CSV import against
  the Docker stack.
- Gates: ruff + mypy `strict` (backend), tsc + oxlint (frontend).
