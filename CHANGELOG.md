# Changelog

## [Unreleased] — M0 Foundation

### Added
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
