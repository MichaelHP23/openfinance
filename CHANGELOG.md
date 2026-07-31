# Changelog

## [Unreleased] — Origin parity program

Planning only so far; no behaviour has changed.

### Added
- `TASK.md` — current phase, gates, and the invariants that outrank convenience, so an
  agent picking this up cold knows what is in flight.
- Design spec for the Origin parity program
  (`docs/superpowers/specs/2026-07-30-origin-parity-design.md`): five sequential phases
  covering categorization, budgets, goals and cash-flow forecasting, a tool-calling AI
  advisor, and reports/tax/document-vault. Credit-score monitoring, CFP access, and a
  high-yield cash account are cut by name — they need a bureau contract, a licensed
  human, and a banking partner respectively.
- Implementation plan for P1, categorization
  (`docs/superpowers/plans/2026-07-30-p1-categorization.md`).

## [Unreleased] — M0 Foundation

### Added
- Daily balance snapshots + net worth over time chart, recorded by a background loop
  that also syncs connections every `SYNC_INTERVAL_HOURS`.
- Optional AI assistant: a computed digest goes to Claude, which interprets but never
  calculates. Hidden entirely without `ANTHROPIC_API_KEY`; `/insights/digest` exposes
  the facts it was given.
- SimpleFIN Bridge provider: claim a setup token, encrypt the access URL, sync accounts
  and transactions with dedup on provider transaction ids. Connect / Sync now / Forget
  in the UI.
- `APP_SECRET_KEY` startup guard — the published default is refused outside development.
- `LOCAL_MODE` single-user desktop mode — no login, one household, guarded to
  `ENVIRONMENT=development`. Compose enables it by default.
- Designed UI: sidebar shell, overview with net worth / cash flow / top merchants,
  accounts and transactions pages.
- Email/password auth: argon2id hashing, opaque server-side sessions, rate-limited
  register/login, `GET /auth/me`.
- Household tenancy — every financial row scoped to `household_id`, with isolation tests.
- `BankProvider` protocol + `ManualProvider`; provider credentials encrypted at rest
  (AES-GCM envelope encryption, AAD bound to household + provider).
- Accounts and categories; transactions with CRUD, filtering, and CSV import with dedup.
- React frontend: auth pages, accounts, transactions, CSV upload.
- Postgres + Redis + API + web via Docker Compose; Alembic migrations run on API start.
- Tests: pytest + testcontainers, vitest, Playwright smoke; ruff, mypy strict, tsc, oxlint.
