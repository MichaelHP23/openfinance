# OpenFinance — Foundation Milestone (M0) Design

**Date:** 2026-07-24
**Status:** Approved for planning
**Scope:** M0 only. Later milestones (M1–M12) listed in the roadmap section; each gets its own spec.

---

## 1. Project context

Greenfield. Goal: production-grade, open-source, self-hostable personal finance platform (rivaling Monarch / Copilot / YNAB) that scales from one user to thousands. This document specs the **foundation milestone** — the spine every later feature bolts onto — plus the milestone roadmap for the rest.

### Locked architectural decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Runtime architecture | Server-authoritative cloud | Postgres server is source of truth. Multi-user, families, background sync, AI all natural. Self-host = run the server. Offline is a later cache layer, not CRDT. |
| Primary DB | PostgreSQL everywhere (incl. local dev) | RLS-friendly, concurrent writes, `NUMERIC` money, JSON parity. No SQLite dev shortcut — it leaks (different migrations/JSON/no RLS). |
| Currency | Single-currency v1, multi-ready schema | Every account/txn carries a `currency` column from day one; no FX logic yet. Cheap insurance against a painful retrofit. |
| Money type | `NUMERIC(19,4)` in DB, `Decimal` in Python | Never float. |
| Tenancy | Household is top-level tenant | Every user belongs to a household (solo = household of 1). All financial data scopes to `household_id`. Roles: owner/member/viewer. Families work day one. |
| Provider abstraction | `BankProvider` / `MarketDataProvider` / `LLMProvider` protocols from day one | Services depend on interfaces, never on Plaid. M0 ships `ManualProvider` only. |
| Background jobs | Dramatiq (Redis broker) | Simpler than Celery, enough for sync/detection jobs. Not used in M0; interface stays sync-callable until M2. |
| Auth v1 | Email+password + server-side sessions | argon2 hashing, httpOnly+SameSite cookies, CSRF on mutations. Clean seams for OAuth/passkeys/2FA (deferred to M10). |
| AI design constraint | LLM calls typed backend tools, never raw SQL | "Never hallucinate numbers" is an architectural constraint on how read services are built, honored from M0 onward. |

---

## 2. M0 purpose

Ship the smallest slice that proves the spine: auth, households, tenancy isolation, encrypted provider credentials, the provider abstraction, and account + transaction core — with **one** provider implementation (`ManualProvider`: manual entry + CSV import). No Plaid, no AI, no investments. All later features reuse these seams unchanged.

---

## 3. Architecture

Monorepo:

```
openfinance/
  backend/          FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2
  frontend/         React 19 + Vite + TypeScript + Tailwind + TanStack Query
  docker-compose.yml  postgres + redis + api + web
  docs/
```

Backend layering (strict — enforced by convention + review):

```
api/        FastAPI routers. Thin. HTTP concerns only (parse, auth dep, call service, serialize).
services/   Business logic. No HTTP, no framework. Unit-testable.
providers/  BankProvider / MarketDataProvider / LLMProvider protocols + implementations.
models/     SQLAlchemy ORM models.
schemas/    Pydantic request/response models.
core/       config, db session, security, encryption, dependencies.
```

**Rule:** routers → services → (providers + models). No business logic in routers. No ORM queries in routers.

---

## 4. Data model (M0)

All financial rows carry `household_id` — the tenancy boundary.

| Table | Key columns |
|-------|-------------|
| `households` | id (uuid pk), name, created_at |
| `users` | id, household_id fk, email (unique, citext), password_hash (argon2), role enum(owner/member/viewer), created_at |
| `sessions` | id, user_id fk, token_hash, expires_at, created_at |
| `provider_connections` | id, household_id fk, provider enum, encrypted_credentials (bytea), status enum(active/error/disconnected), last_synced_at nullable |
| `accounts` | id, household_id fk, connection_id fk nullable, type enum(checking/savings/credit_card/loan/investment/crypto/cash/asset/liability), name, institution nullable, currency char(3) default 'USD', balance NUMERIC(19,4), is_manual bool, created_at |
| `categories` | id, household_id fk nullable (null = system default), name, parent_id fk nullable |
| `transactions` | id, household_id fk, account_id fk, posted_at, amount NUMERIC(19,4), currency char(3), merchant_raw, merchant_normalized nullable, category_id fk nullable, notes nullable, external_id nullable (provider dedup key), created_at |

Notes:
- PKs are UUIDs (portable across future sharding/merge, non-enumerable in URLs).
- `transactions.external_id` unique per `(connection_id, external_id)` when present → dedup seam for M2 Plaid sync.
- Money: `NUMERIC(19,4)`; Python side uses `Decimal`. Currency present but single-currency enforced in service layer for v1.
- Signed amounts: negative = outflow, positive = inflow (documented convention).

---

## 5. Provider abstraction (the key seam)

```python
from typing import Protocol

class BankProvider(Protocol):
    name: str
    def link_account(self, household_id, credentials) -> ProviderConnection: ...
    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]: ...
    def fetch_transactions(self, conn: ProviderConnection, since) -> list[TxnDTO]: ...
```

- M0 implementation: **`ManualProvider`** — accounts created by hand, transactions entered manually or via CSV import. `fetch_*` operate on stored manual data.
- `PlaidProvider` (M2) implements the same protocol → **zero service changes**. MX/GoCardless/Coinbase (deferred) likewise.
- `MarketDataProvider` and `LLMProvider` protocols are declared in M0 (empty/stub impls) so later milestones slot in without touching M0 code.

DTOs (`AccountDTO`, `TxnDTO`) decouple provider payloads from ORM models.

---

## 6. Security (M0)

- **Passwords:** argon2id hashing (`argon2-cffi`).
- **Sessions:** server-side (`sessions` table), opaque token in httpOnly + SameSite=Lax + Secure cookie. No JWT in v1.
- **CSRF:** M0 mitigation is `SameSite=Lax` session cookies (blocks classic cross-site CSRF). Full double-submit CSRF token on all state-changing requests is **deferred to M10 (Auth hardening)**, added once with frontend support in a single coherent pass.
- **Credential encryption at rest:** envelope encryption. KEK from `APP_SECRET_KEY` env var; per-connection DEK; ciphertext + wrapped DEK stored in `provider_connections.encrypted_credentials`. Lives in `core/encryption.py`. AES-GCM (`cryptography` lib).
- **Rate limiting:** auth endpoints throttled (slowapi + Redis).
- **Tenancy enforcement:** a `require_household` FastAPI dependency resolves `household_id` from the session; every service query filters by it. No endpoint can read cross-household. Covered by explicit isolation tests.
- **Secrets:** all via env / `.env` (gitignored); `.env.example` documents keys. No secrets in code or repo.

---

## 7. Testing

- **Backend:** pytest + `testcontainers[postgresql]` — tests run against real Postgres, not mocks. TDD: test first per feature.
  - Every service method tested.
  - **Tenancy isolation tests are mandatory:** assert user in household A cannot read/write household B's accounts, transactions, connections.
  - Encryption round-trip test (`encrypt` → store → `decrypt` == original).
- **Frontend:** vitest for units; one Playwright smoke: register → login → create manual account → add transaction → CSV import → see transactions listed and filtered.
- **Quality gates:** ruff (lint+format) + mypy on backend; eslint + tsc on frontend. All green before milestone close.

---

## 8. M0 Definition of Done

1. `docker compose up` brings up postgres + redis + api + web.
2. User can: register → login → (household auto-created as household-of-1) → create manual account → add transactions manually and via CSV import → list, filter, edit, delete transactions.
3. `provider_connections.encrypted_credentials` proven end-to-end with `ManualProvider` (even if manual creds are trivial, the encryption path is exercised).
4. `BankProvider` protocol in place; `ManualProvider` is the sole impl; services depend only on the protocol.
5. Tenancy isolation enforced and tested.
6. Alembic migrations produce the schema from scratch.
7. ruff + mypy + eslint + tsc + pytest + vitest + Playwright smoke all green.
8. Docs started: `README.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, `.env.example`. Meaningful git commits.

---

## 9. Milestone roadmap (each = its own spec → plan → build)

| Milestone | Contents |
|-----------|----------|
| **M0 Foundation** | This document. |
| **M1 Transactions UX** | Bulk edit, split transactions, tags, notes, rules engine, categorization, duplicate detection, merchant normalization. |
| **M2 Plaid + real sync** | `PlaidProvider`, Dramatiq sync jobs, sync history, connection status, institution logos. |
| **M3 Budgets** | Category + envelope budgeting, monthly rollover, custom periods, spending forecasts. |
| **M4 Dashboard + net worth** | Net worth history, cash flow, savings rate, financial health score, summary tiles, upcoming bills. |
| **M5 Investments** | Holdings, cost basis, allocation (sector/industry/geo/asset), performance, `MarketDataProvider` (Yahoo/Alpha Vantage), benchmarks, realized/unrealized gain-loss, dividends, risk metrics, allocation drift. |
| **M6 AI assistant** | `LLMProvider` (Claude) + typed financial tools over read services. Never raw SQL, never hallucinated numbers. |
| **M7 Goals** | Savings, debt payoff, emergency fund, vacation/investment/mortgage/student-loan; avalanche/snowball/custom strategies. |
| **M8 Reports + export** | Income vs expenses, trends, category/merchant/subscription analysis, net worth history, tax reports, CSV + PDF export. |
| **M9 Automation** | Recurring/subscription/income/transfer detection, subscription price-increase alerts, anomaly detection. |
| **M10 Auth hardening** | CSRF double-submit tokens (deferred from M0), OAuth providers, passkeys, 2FA, RBAC expansion, audit logs, session management UI. |
| **M11 Plugin system** | Extension boundary decision (subprocess/WASM sandbox), plugin API for importers/reports/providers/dashboards/AI tools/notifications. |
| **M12 Mobile / PWA** | Responsive polish, PWA install, offline read cache. React Native later, reusing the same API. |

**Deferred (YAGNI until real users / demand):** premium features; MX / GoCardless / Coinbase / Kraken / Venmo / PayPal / wallet providers (interface already supports them); CRDT true-local-first sync mode.

---

## 10. Design principles carried through every milestone

- Small, single-purpose units communicating through well-defined interfaces; each independently testable.
- Provider adapters, not hardcoded vendors.
- `Decimal` money, never float; `household_id` on every financial row.
- LLM sees typed tools, never raw data or SQL.
- Every milestone ends production-ready: tests + lint green, docs + CHANGELOG updated, meaningful commits.
