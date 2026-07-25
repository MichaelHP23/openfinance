# OpenFinance

A personal finance tracker you run yourself. Accounts, transactions, CSV import from
your bank, and an overview of where the money actually goes — on your machine, in your
Postgres, with nothing phoning home.

FastAPI over PostgreSQL, React 19 frontend. Money is `NUMERIC(19,4)` / `Decimal` end to
end, never float. Every financial row is scoped to a household, and provider credentials
are encrypted at rest — so the same code runs multi-user if you ever want it to, but the
default install is single-user with no login.

*(`openfinance` is a working name.)*

## Quickstart

```bash
cp backend/.env.example backend/.env   # then set APP_SECRET_KEY
docker compose up -d
```

Open http://localhost:5173. There's no sign-up — see local mode below.

- API → http://localhost:8000 (docs at `/docs`)
- Web → http://localhost:5173
- Postgres → `localhost:5433` (5432 inside the network)

Migrations run automatically when the `api` container starts.

## Local mode

Compose sets `LOCAL_MODE=true`, which runs the whole app as one household with **no
login at all** — a single-user desktop install shouldn't make you authenticate against
yourself. The local household is created on first request.

This means anyone who can reach the API can read and write your finances, so it only
holds while the ports stay bound to localhost. The API refuses to start with
`LOCAL_MODE=true` unless `ENVIRONMENT=development`.

Putting this on a network? Set `LOCAL_MODE=false` and the email/password auth
(argon2id, server-side sessions, rate limits) takes over — `/register` and `/login`
are already built and tested.

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

## What's here

- **Overview** — net worth, monthly cash flow, top merchants, recent activity.
- **Accounts** — nine account types, assets and liabilities netted correctly.
- **Transactions** — manual entry, merchant search, CSV import that dedups on re-import.
- Local mode (no login) or full email/password auth: argon2id, server-side sessions,
  rate limits.
- `BankProvider` protocol with a `ManualProvider`; credentials sealed with AES-GCM
  envelope encryption bound to the household + provider context.

## Not here yet

- **Bank syncing.** Needs Plaid API keys — that's the next milestone. Until then,
  import your bank's CSV export.
- Budgets, categorization rules, investments, reports. See the roadmap in the design spec.

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [M0 design spec](docs/superpowers/specs/2026-07-24-foundation-m0-design.md)
- [M0 implementation plan](docs/superpowers/plans/2026-07-24-m0-foundation.md)
- [Changelog](CHANGELOG.md)
