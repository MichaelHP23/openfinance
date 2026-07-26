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

## Connecting a bank

Bank syncing goes through [SimpleFIN Bridge](https://beta-bridge.simplefin.org/) — a
read-only aggregation protocol that costs about $15/year and needs no application or
business review, unlike Plaid.

1. Link your banks at SimpleFIN Bridge and copy the **setup token** it gives you.
2. Paste it into **Accounts → Connect a bank**.

The token is single-use: the app exchanges it for a durable access URL, encrypts that
with AES-256-GCM, and stores only the ciphertext. Hit **Sync now** to pull new
transactions; re-syncing is deduped on the provider's own transaction ids, so nothing
doubles up.

Plaid slots into the same `BankProvider` protocol if SimpleFIN doesn't cover your bank.

## Reaching it from your phone

The app has **no login** in local mode, so it must never be port-forwarded or given a
public hostname — anyone who found it would have full access to your finances.

Use a private network instead. [Tailscale](https://tailscale.com/) is the easy one:
install it on this machine and on your phone, sign both into the same account, then
open `http://<machine-name>:5173` from the phone anywhere in the world. Nothing is
exposed publicly and no ports are opened.

On your own wifi, the LAN address works with no extra software: `http://<lan-ip>:5173`.

The client derives the API host from whatever address you loaded the page on, so no
configuration changes between localhost, LAN and tailnet. In development the API
accepts origins from loopback, RFC1918 LAN ranges and Tailscale (100.64/10, `*.ts.net`)
— public origins still have to be listed explicitly in `CORS_ORIGINS`.

Your machine has to be awake with `docker compose up -d` running for any of this to
answer.

## AI assistant

Optional and off by default. Put an `ANTHROPIC_API_KEY` in `backend/.env` and a
"What's up with my money" card appears on the overview; without a key the endpoint
reports itself unavailable and the UI hides it, so nothing leaves your machine.

The assistant never sees your raw transactions and never does arithmetic. The app
computes a digest — net worth, per-month income and spending, top merchants, largest
transactions, likely subscriptions — and the model is given only that, with
instructions that every figure it cites must come from it. `GET /insights/digest`
returns those exact facts so you can check any claim it makes.

Enabling it does mean a summary of your finances is sent to Anthropic's API.

## Background sync

The API runs a loop every `SYNC_INTERVAL_HOURS` (default 6) that syncs every
connection and records a **daily balance snapshot** per account. Those snapshots are
what the net-worth-over-time chart draws — balances are only knowable in the present,
so a day that isn't recorded is lost. Set the interval to `0` to disable.

## Not here yet

- Budgets, categorization rules, investments holdings, reports. See the roadmap in the
  design spec.
- Scheduled background syncing — for now, syncing is a button.
- Editing or deleting an account from the UI.

## Don't run `npm audit fix --force`

`react-router-dom` is pinned to 7.18.1 with an `overrides` entry. `--force` "fixes" it by
downgrading to 7.11.0, which trades one advisory for fourteen — including an RCE and
several XSS/DoS — and then audit tells you to `--force` back. It loops.

7.18.1's only advisory is [GHSA-qwww-vcr4-c8h2](https://github.com/advisories/GHSA-qwww-vcr4-c8h2),
an RSC-mode CSRF bypass. This is a plain SPA with no RSC, so it doesn't apply. `npm audit`
can't tell, because it matches version ranges, not usage. Revisit when a 7.x release clears it.

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [M0 design spec](docs/superpowers/specs/2026-07-24-foundation-m0-design.md)
- [M0 implementation plan](docs/superpowers/plans/2026-07-24-m0-foundation.md)
- [Changelog](CHANGELOG.md)
