# Current work

**Program:** Origin parity — build what [Origin Financial](https://useorigin.com/) sells,
minus the three pillars that need a vendor or a license, minus credit-score monitoring.

**Spec:** `docs/superpowers/specs/2026-07-30-origin-parity-design.md` — approved.
Read it before touching any phase. It records what was cut and why, which matters more
than what was kept.

## Phase status

| Phase | What it is | Plan | State |
|---|---|---|---|
| **P1** | Categorization engine — rules, system taxonomy, auto-apply, backfill | `docs/superpowers/plans/2026-07-30-p1-categorization.md` | **In progress on branch `p1-categorization`.** Task 1 of 12 done and reviewed clean. |
| P2 | Budgets — monthly, rollover on read, median suggest | not yet written | Blocked on P1 |
| P3 | Goals + daily cash-flow forecast + `can_i_afford` | not yet written | Blocked on P2 |
| P4 | AI advisor v2 — read-only tool calling, visible call trace | not yet written | Blocked on P1–P3 |
| P5 | Reports, FIFO realized gains, encrypted document vault, full export | not yet written | Independent, scheduled last |

Phases are strictly sequential. Each phase's full test suite must pass before the next
begins.

## Starting P1

The plan is 12 tasks, each ending in a commit. Execute it with
`superpowers:subagent-driven-development` (fresh subagent per task) or
`superpowers:executing-plans` (inline, batched). Do not freelance around the plan —
it encodes decisions from the spec that are not obvious from the code.

Read these before the first task:

- `backend/app/models/category.py` — the table has existed since M0 and is empty.
  `transactions.category_id` already points at it. P1 fills a hole, it does not cut one.
- `backend/app/services/recurring.py::merchant_key` — the normalization P1 reuses.
  Do not write a second one.
- `backend/tests/conftest.py` — tests build the schema with `Base.metadata.create_all`,
  **not** Alembic. Seed data that only lives in a migration is invisible to every test.

## Invariants that outrank convenience

- Money is `Decimal` in Python, `NUMERIC(19,4)` in Postgres. Never `float`.
- Every financial row carries `household_id`; every service function filters on it.
  `backend/tests/test_tenancy.py` exists to catch the lapses.
- The LLM never calculates and never writes. It proposes; the user confirms; the app
  writes. This is architectural, from M0 onward — not a style preference.
- No new dependencies. Everything planned uses what is already installed.
- `LOCAL_MODE=true` requires `ENVIRONMENT=development`; the app refuses to start
  otherwise, because local mode has no authentication at all.

## The lint gates do not currently pass, and that is not your change

`ruff check app tests` reports **129 errors**; `mypy app` reports **24**. All pre-existing,
none from P1. They live in `app/services/portfolio.py`, `app/services/trade_import.py`,
`app/core/scheduler.py`, and `tests/test_trades.py` — mostly `FURB157`
(`Decimal("1")` → `Decimal(1)`) and a cluster of real `object`-typed arithmetic in
`portfolio.py` that mypy is right about.

So the working gate is **"no new errors in the files you touched"**, not "clean". Check by
running the tool before and after your change. 122 of the ruff errors are `--fix`-able in
one command; the `portfolio.py` mypy cluster is a genuine typing bug worth its own fix.
The README's claim that these gates pass is stale.

## Gates

Backend needs Docker running — the test suite spins up a real `postgres:17` container.
Start Docker Desktop first; without it every backend test fails at container spinup, which
looks like a code failure and is not.

```bash
cd backend
.venv/Scripts/python -m pytest          # POSIX: .venv/bin/python
.venv/Scripts/python -m ruff check app tests
.venv/Scripts/python -m mypy app

cd ../frontend
npm test
npm run typecheck
npm run lint
npm run e2e      # needs `docker compose up -d` + `npm run dev`
```

All six must pass before claiming a phase done. Paste the output; do not assert it.

## Deliberate deviations from the spec

Recorded here so nobody "fixes" them:

- **The spec asks for a Rules page. The plan puts rules on the Transactions page.**
  `frontend/src/ui/Shell.tsx` documents five tabs as the mobile bar's hard ceiling, and
  rules are only ever reached from looking at transactions.
- **`POST /category-rules/preview` ships without a button.** The endpoint and its test
  are in P1 Task 7; no UI calls it. The add-rule form is one line and deleting a bad
  rule is one click, so a preview step in front of it is friction. Wire it up if writing
  rules turns out to be error-prone in practice.
