# OpenFinance

Self-hosted household finance tracking. Server-authoritative FastAPI backend over
PostgreSQL, React 19 frontend. Every financial row is scoped to a household, provider
credentials are encrypted at rest, and money is `NUMERIC(19,4)` / `Decimal` end to end.

*(`openfinance` is a working name.)*

## Quickstart

```bash
cp backend/.env.example backend/.env   # then set APP_SECRET_KEY
docker compose up -d
```

- API → http://localhost:8000 (docs at `/docs`)
- Web → http://localhost:5173
- Postgres → `localhost:5433` (5432 inside the network)

Migrations run automatically when the `api` container starts.

## Local development

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # POSIX: .venv/bin/python
.venv/Scripts/python -m pytest          # needs Docker: tests spin up a real Postgres
.venv/Scripts/python -m ruff check app tests
.venv/Scripts/python -m mypy app

# frontend
cd frontend
npm install
npm run dev
npm test          # vitest
npm run e2e       # playwright, needs `docker compose up -d` + the dev server
npm run typecheck
npm run lint
```

## What's here (M0)

- Email/password auth: argon2id hashes, opaque server-side session cookies, rate limits.
- Household tenancy: every account/transaction read and write filters on `household_id`.
- `BankProvider` protocol with a `ManualProvider`; credentials sealed with AES-GCM
  envelope encryption bound to the household + provider context.
- Accounts, categories, transactions (manual entry, filtering, CSV import with dedup).

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [M0 design spec](docs/superpowers/specs/2026-07-24-foundation-m0-design.md)
- [M0 implementation plan](docs/superpowers/plans/2026-07-24-m0-foundation.md)
- [Changelog](CHANGELOG.md)
