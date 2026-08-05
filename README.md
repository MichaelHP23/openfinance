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
cp .env.example .env                   # TS_IP — the address the stack publishes on
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
- **Categories** — a rule list that sorts transactions as they arrive, from CSV import or
  from a bank sync. Rules match on merchant, amount, and account; the first one in the
  list wins, and you can reorder them. Nothing is a black box: every category on a
  transaction traces to a rule you can open.
- **Budgets** — a monthly amount per category, with actual spend, remaining, and a pace
  indicator (spend-fraction vs. calendar-fraction) computed live, never guessed. Turning
  on rollover folds last month's unspent amount into this one; the carry is recomputed
  from history every time it's shown and nothing is ever written for it, so switching
  rollover off can't corrupt a number you already saved. Suggest fills in a trailing
  3-month median, rounded to the nearest 5 — no model involved.
- **Goals** — savings and debt-payoff targets, linked to the real accounts that fund
  them; progress is always today's actual balance, never a separate ledger that can
  drift from it. A cash-flow forecast on Overview projects forward from today's
  balances, your recurring bills, and this month's budget — with a "can I afford…"
  check that shows what a hypothetical purchase does to the projection and whether
  the balance stays non-negative. (The API also computes the impact on every active
  goal's projected date; the UI doesn't surface that part yet.)
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

The app runs on an always-on cloud instance that has joined a
[Tailscale](https://tailscale.com/) network. Install Tailscale on your phone, sign it into
the same account, and open `http://openfinance:5173` from anywhere.

**Your PC does not need to be on.** It is just another client on the tailnet, the same as
the phone. The instance holds Postgres, the API and the background scheduler, so syncing
and daily balance snapshots continue whatever your desktop is doing.

Nothing is exposed to the public internet — the instance's public IP has no listening
port, and the only route in is the tailnet. That is what makes it safe for the app to have
**no login at all** in local mode. The flip side: a device without Tailscale cannot reach
it, so there is no showing this to someone on their own laptop.

The client derives the API host from whatever address you loaded the page on, so nothing
is configured per-device. In development the API accepts origins from loopback, RFC1918
LAN ranges and Tailscale (100.64/10, `*.ts.net`); the bare MagicDNS short name
(`http://openfinance:5173`) needs listing in `CORS_ORIGINS`, which the deploy sets.

Full design and the provisioning runbook:
`docs/superpowers/specs/2026-07-29-oracle-hosting-design.md`.

## Local development

The `web` container serves a **built** bundle and does not hot-reload. For the frontend dev
loop, run Vite directly and use compose for the backing services:

```bash
docker compose up -d postgres redis api
cd frontend && npm run dev
```

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

The assistant can also propose categories for merchants it hasn't seen sorted. That call
sends merchant *names* and the category list — no amounts, no dates, no accounts — and
its proposals are written only for the ones you tick.

## Background sync

The API runs a loop every `SYNC_INTERVAL_HOURS` (default 6) that syncs every
connection and records a **daily balance snapshot** per account. Those snapshots are
what the net-worth-over-time chart draws — balances are only knowable in the present,
so a day that isn't recorded is lost. Set the interval to `0` to disable.

## Not here yet

- Reports. See the roadmap in `docs/superpowers/specs/2026-07-30-origin-parity-design.md`.
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
