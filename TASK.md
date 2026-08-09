# Current work

**Program:** Origin parity — build what [Origin Financial](https://useorigin.com/) sells,
minus the three pillars that need a vendor or a license, minus credit-score monitoring.
**Shipped and merged to `main` as of 2026-08-09** (P1–P5, see Phase status below).

**Next program:** Post-parity roadmap — auth hardening, mobile/PWA, and a plugin system
(the three M0 milestones the origin-parity program left untouched).

**Spec:** `docs/superpowers/specs/2026-07-30-origin-parity-design.md` for P1–P5 (closed).
`docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` for P6–P8 (current).
Read the relevant one before touching any phase. Both record what was cut and why, which
matters more than what was kept.

## Phase status

| Phase | What it is | Plan | State |
|---|---|---|---|
| P1 | Categorization engine — rules, system taxonomy, auto-apply, backfill | `docs/superpowers/plans/2026-07-30-p1-categorization.md` | **Shipped, merged to `main`.** |
| P2 | Budgets — monthly, rollover on read, median suggest | `docs/superpowers/plans/2026-07-31-p2-budgets.md` | **Shipped, merged to `main`.** |
| P3 | Goals + daily cash-flow forecast + `can_i_afford` | `docs/superpowers/plans/2026-08-01-p3-goals-forecast.md` | **Shipped, merged to `main`.** |
| P4 | AI advisor v2 — read-only tool calling, visible call trace | `docs/superpowers/plans/2026-08-01-p4-ai-advisor-v2.md` | **Shipped, merged to `main`** 2026-08-09 (was on branch `p4-ai-advisor-v2`). |
| P5 | Reports, FIFO realized gains, encrypted document vault, full export | `docs/superpowers/plans/2026-08-01-p5-reports-tax-vault.md` | **Shipped, merged to `main`** 2026-08-09 (was on branch `p5-reports-tax-vault`). |
| **P6** | Auth hardening — CSRF, session rotation/revoke, TOTP 2FA, RBAC enforcement, audit log | not yet written | **Starting now.** Independent of P7/P8. |
| P7 | Mobile/PWA — installable, offline read cache, fixes the pre-existing `mobile.spec.ts` bug | not yet written | Independent, queued after P6 |
| P8 | Plugin system | not yet written | Blocked on a written answer to the post-parity spec's §5.3 scope check — may be deferred indefinitely |

P1–P5 were strictly sequential; that constraint doesn't apply to P6–P8, which have no
data-model dependencies on each other (see post-parity spec §6). They're being done in
value order, not dependency order.

## Starting P6

Read `docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` §2 before writing
the implementation plan. Ground truth already verified there against the tree: sessions
are a sha256-hashed token in an httpOnly cookie with a 30-day TTL
(`backend/app/services/auth.py`), there is no CSRF token anywhere (`SameSite=Lax` only),
`User.role` (`owner`/`member`) exists but nothing checks it yet, and `LOCAL_MODE` has zero
authentication by design (`app/main.py:33-40`) — P6 must not add friction to that path.

Write the implementation plan with `superpowers:writing-plans`, following the format of
`docs/superpowers/plans/2026-07-30-p1-categorization.md` (the shipped exemplar
`PLAN-CONSTRAINTS.md` names), then execute it with `superpowers:subagent-driven-development`
or `superpowers:executing-plans`. Do not freelance around the plan.

## Starting P1 (historical — kept for the file paths and invariants, still accurate)

Read these before touching categorization-adjacent code:

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

`ruff check app tests` reports **174 errors** (as of 2026-08-09, after P4/P5 merged —
was 129 before); `mypy app` reports **24**. All pre-existing. They live in
`app/services/portfolio.py`, `app/services/trade_import.py`, `app/core/scheduler.py`, and
`tests/test_trades.py` — mostly `FURB157` (`Decimal("1")` → `Decimal(1)`) and a cluster of
real `object`-typed arithmetic in `portfolio.py` that mypy is right about.

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

All seven must pass before claiming a phase done. Paste the output; do not assert it.

`npm run e2e` currently runs `smoke.spec.ts`, `mobile.spec.ts`, and (as of P1)
`categorization.spec.ts`. `mobile.spec.ts` fails on `main` as of this writing —
`getByRole("heading", { name: "Accounts" })` on the Accounts page matches both the page's
`<h1>` and the "Your accounts" `<h2>` card title, a strict-mode violation predating P1 and
unrelated to categorization (`AccountsPage.tsx` has no P1 commits). `smoke.spec.ts` and
`categorization.spec.ts` pass. Worth its own fix; not blocking P1.

## Deliberate deviations from the spec

Recorded here so nobody "fixes" them:

- **The spec asks for a Rules page. The plan puts rules on the Transactions page.**
  `frontend/src/ui/Shell.tsx` documents five tabs as the mobile bar's hard ceiling, and
  rules are only ever reached from looking at transactions.
- **`POST /category-rules/preview` ships without a button.** The endpoint and its test
  are in P1 Task 7; no UI calls it. The add-rule form is one line and deleting a bad
  rule is one click, so a preview step in front of it is friction. Wire it up if writing
  rules turns out to be error-prone in practice.
