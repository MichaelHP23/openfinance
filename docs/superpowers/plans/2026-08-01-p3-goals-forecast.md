# P3 Goals and Cash-Flow Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A household can set a savings or debt-payoff target, link the real accounts that count toward it, and see — from today's actual balances and its own recurring bills, not a model's guess — whether it's on pace, when it projects to land, and whether a hypothetical purchase would put the account in the red before then.

**Architecture:** `goals` is one row per target with a `goal_accounts` join table saying which account balances count toward it — no separate contributions ledger, because a ledger of "money you say you put toward the goal" that can disagree with the linked account's real balance is a bug factory, not a feature. Progress is always `progress_for()`, computed fresh from the linked accounts' current balances every time it's asked, sign-flipped for `debt_payoff` (progress there is how much of the original `target_amount` has been paid down, not the balance itself).

`services/forecast.py` is the other half: `project()` starts at today's summed cash-account balances and walks forward one day at a time through the requested horizon, applying every active `RecurringSeries` whose cadence lands on that day and a flat daily rate for discretionary spend — the current month's budgeted total for categories no recurring series already covers, spread evenly. Every day in the resulting series carries a `contributions` list naming exactly what moved the balance, so any point on the chart traces back to a real row: a recurring series, a budget, a hypothetical the user typed in. `can_i_afford()` runs `project()` twice — with and without a hypothetical outflow — and reports whether the balance would go negative and what it does to every active goal's projected date. Nothing here is a strategy engine or a simulation; it's arithmetic over rows that already exist.

**Tech Stack:** FastAPI, SQLAlchemy 2 (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + testcontainers Postgres, React 19, TanStack Query, Vitest, Playwright.

---

## STOP — read this before Task 1

This plan implements **P3**, which the spec (`docs/superpowers/specs/2026-07-30-origin-parity-design.md`, §5 "P3 — Goals and cash-flow forecast") states depends on **P2 (Budgets)**: step 3 of `project()` needs `app.services.budgets.status()` and `app.models.budget.Budget`, and §7 of the spec says phases are "strictly sequential; each phase's tests must pass before the next begins."

**As of the date this plan was written (2026-08-01), P2 has not merged.** This was verified directly, not assumed:

- `backend/app/models/budget.py` does not exist. `backend/app/services/budgets.py` does not exist. `backend/app/api/budgets.py` does not exist.
- `backend/app/models/__init__.py` has no `Budget` import.
- `backend/migrations/versions/` has no `c8a4f21d9b6e_budgets.py` — the file P2's own plan (`docs/superpowers/plans/2026-07-31-p2-budgets.md`) specifies. `cd backend && .venv/Scripts/python -m alembic heads` returns `e1f3a2c4b508` (P1's last migration), not P2's.
- `frontend/src/ui/Shell.tsx` still has its original five-entry `NAV` array (Overview, Accounts, Investments, Transactions, Recurring) — no `MoreMenu.tsx`, no `MORE` array. `git log`/`git branch -a` show only `main`, `p1-categorization`, and `oracle-hosting`; there is no `p2-budgets` branch anywhere. `CHANGELOG.md` says explicitly: "P1 (categorization) is complete on the `p1-categorization` branch. Nothing has merged to `main` yet."
- `frontend/package.json` has no `recharts` dependency either, despite the spec's cross-cutting §6 claiming "every phase uses ... Recharts, all already installed." The codebase's actual chart library is a hand-rolled `frontend/src/charts.tsx` (`AreaChart`, `BarChart`, `AllocationBar`, plain SVG). This plan builds against what's really there.

**This plan is written assuming P2 merges before execution reaches Task 5.** Tasks 1–4 (the `Goal`/`GoalAccount` models, goals CRUD, goal progress, and the recurring-cadence walk with hypotheticals) touch nothing P2 owns and can be built and tested today regardless of P2's status. **Before starting Task 5, re-run the verification above** (`ls backend/app/models/budget.py`, `.venv/Scripts/python -m alembic heads`). If P2 still hasn't merged, stop — do not stub out `budgets.status()` or invent a fake return shape. Wait for P2, or get it merged first. Task 5's code and every task after it cites `budgets.status()`'s real signature and its `CategoryBudgetStatus` dataclass exactly as P2's own plan document defines them (`docs/superpowers/plans/2026-07-31-p2-budgets.md`, Task 3) — if P2's actual implementation ends up differing from its own plan by the time it merges, treat every P2-derived signature in this document as approximate and adjust, but the boundary (Tasks 1–4 are P2-independent; Task 5 onward is not) does not move.

**Task 14 (navigation) has the same problem for a different file.** PLAN-CONSTRAINTS.md instructs P3 to add one entry to an existing `MORE` array in `Shell.tsx` that P2 was supposed to have already built. It hasn't. Task 14 gives an explicit two-branch instruction for whichever state is real at execution time — see that task; it is not a guess written on top of code that isn't there.

---

## Global Constraints

Carried forward from `docs/superpowers/plans/PLAN-CONSTRAINTS.md`, restated for this plan:

- **Money** is `Decimal` in Python and `NUMERIC(19,4)` in Postgres, and a **string** once it crosses into TypeScript. Never `float`, never `number`. `goals.target_amount`, `goals.monthly_funding`, every `ForecastDay.projected_balance`, and every dollar figure in a `contributions` string follows this.
- **Tenancy.** Every function in `services/goals.py` and `services/forecast.py` takes `household_id` and filters on it. A user-supplied `account_id` (linking an account to a goal) is checked with `accounts.get(db, household_id, account_id)` before it is ever written — an unknown id or a foreign household's account is a `422` via a typed `UnknownAccount` exception, never a 500. A user-supplied `goal_id` that doesn't resolve for this household is a typed `UnknownGoal` exception, also 422/404 depending on the route (see Task 9). `backend/tests/test_tenancy.py` gets a goals case in Task 10.
- **No new dependencies.** No Recharts (it isn't installed — see the STOP section above); the forecast chart and "can I afford" UI are built on the existing `frontend/src/charts.tsx` (`AreaChart`) and plain SVG, the same way `NetWorthChart` in `frontend/src/insights.tsx` already is.
- **The gates**, from `backend/`: `.venv/Scripts/python.exe -m pytest -q`, `.venv/Scripts/python.exe -m ruff check app`, `.venv/Scripts/python.exe -m mypy app`. From `frontend/`: `npm test`, `npm run build`, `npm run lint`.
- **`npm run build`, never `npm run typecheck`.** `typecheck` is `tsc --noEmit`; `build` is `tsc -b`, and they check different things — P1 shipped behind a green `typecheck` while `build` had been broken the whole time. Every gate step in this plan says `build`.
- **Pre-existing baseline, not this plan's to fix:** `ruff check app` reports 3 and `mypy app` reports 24 pre-existing errors in `portfolio.py`, `trade_import.py`, `scheduler.py`, `investments.py`, `prices.py`, `recurring.py`. The gate is **no new errors in files this plan touches.** `frontend/e2e/mobile.spec.ts` is pre-existing-broken (a non-exact heading matcher) and not this plan's concern.
- **Backend tests need Docker running** — `conftest.py` starts a real `postgres:17` container.
- **Test fixtures.** `backend/tests/conftest.py` provides only `pg_engine` and `db`. There is no shared `household` or `account` fixture. Every test file this plan creates defines its own, following the shape already in `backend/tests/test_budgets_api.py` and `backend/tests/test_recurring.py` — not shared across files.
- **Tests build the schema with `Base.metadata.create_all`, never with Alembic.** Goals need no seed data, so this mostly matters for `test_migrations.py`, which does run the real Alembic chain.
- **Vite module resolution.** `./goals` resolves to `goals.ts` before `goals.tsx`. The component that renders goal cards and progress rings is named `GoalCards.tsx`, not `goals.tsx`, for the same reason `BudgetBoard.tsx` isn't named `budgets.tsx`. Likewise `forecast.ts` (hooks) and `ForecastChart.tsx` (component) are two different files.
- **React Testing Library.** `findByLabelText` on a `<select>` resolves as soon as the element exists, before an async options fetch has resolved — await the *option*, not the select, if a test needs one (Task 12's account-linking `<select multiple>` does). `waitFor` returns on its first truthy check, so a regression assertion that starts out already true is a false negative.
- **House style.** Service modules are flat functions taking `(db, household_id, ...)`. Routers are thin and translate service exceptions into `HTTPException`. Comments explain *why*, never *what*. A deliberate shortcut with a known ceiling gets a `ponytail:` comment naming the ceiling and the upgrade path. One Alembic revision for this phase. Commit subjects are lowercase and human, no task numbers.
- **The cut list is explicit and binding.** Per the spec's own §5 P3 section: avalanche/snowball debt-payoff strategy engines, Monte Carlo simulation, and retirement projection are **cut**. None of the fourteen tasks below build any of them, and if a review of this plan finds one sneaking in under another name, that's a bug in the plan, not a feature to keep.

**Deviations from the spec's literal wording, recorded here rather than silently, mirroring how P2 recorded its own:**

1. **No `updated_at` column.** The spec lists `goals` columns ending "`created_at, updated_at`". Every model in this codebase (`Category`, `Budget` per its own plan, `Transaction`, `Account`, `Household`, `RecurringSeries`) uses `TimestampMixin`, which defines **only** `created_at` (`backend/app/models/base.py:17-18`) — no model anywhere tracks `updated_at`. `Goal` is not the first exception; it uses `TimestampMixin` like everything else and has no `updated_at` column, exactly as P2's plan already decided for `Budget`. If `updated_at` is wanted later it's a mixin change touching every model at once, not a one-table special case invented here.
2. **"Debt paid down from the starting balance" reads as `target_amount` minus the current owed amount, not a stored starting-balance column.** The spec's schema has no column for a debt goal's original balance, and adding one invents a second source of truth for what's really just "how much is left." `progress_for()` (Task 3) treats `target_amount` itself as the amount that was owed when the goal was created — `progress = target_amount - sum(abs(balance) for each linked account)`. A `debt_payoff` goal whose `target_amount` isn't the original debt (e.g., it's set to some other number) will show a progress figure that reads oddly, but that's a data-entry problem, not a modeling gap the UI hides.
3. **A goal with no linked accounts reads zero progress for *either* kind**, not `target_amount` for `debt_payoff` (which the deviation-2 formula would otherwise produce from an empty sum: `target_amount - 0 = target_amount`, i.e. "fully paid," which is a wrong answer to have as a default for a goal nobody's linked an account to yet). `progress_for()` special-cases the empty-accounts case to zero before applying the debt-payoff formula. This is exactly the spec's own explicit forecast test case, "goal with no linked accounts" — see Task 3.
4. **"Stays above zero" (spec's exact wording for `can_i_afford`'s verdict) is implemented as `>= 0`, and the field is named `stays_non_negative`, not `stays_positive`.** An amount that exactly empties the account to `0.00` is the literal spec test case ("`can_i_afford` on an amount that empties the account") and reads naturally as "yes, barely" — treating exactly-zero as a failure would make that named test case fail by design. Overdrafting (going below zero) is the actual problem `can_i_afford` exists to catch.
5. **Discretionary spend (step 3 of `project()`) is computed once, from *today's* month, and held constant as a flat daily rate for the whole projection horizon** — not recomputed per calendar month as the walk crosses into February, March, etc. The spec's own wording says "the current month's budgeted amounts" (singular), and P2's `budgets` table only ever has rows for months a household actually opened the Budgets page and saved — a forecast six months out would have five months with no budget row at all to recompute from. One rate, from the one month that's guaranteed to have data, spread over the whole horizon, is what "current month's" literally says and the only version that doesn't silently go to zero for every month beyond the first.
6. **"Cash-account balances" (spec's forecast step 1) is defined as `checking`, `savings`, and `cash` account types** (`CASH_ACCOUNT_TYPES` in `services/forecast.py`, Task 4) — not `investment`, `crypto`, `asset`, or any of the three liability types. The spec doesn't enumerate which of the app's nine `AccountType` values count as "cash"; net worth (already shipped, `services/snapshots.py`) already answers "what's my whole balance sheet," so the forecast deliberately answers a narrower question — "how much spendable cash will I have" — and investment/crypto marks or a mortgage balance would answer neither question correctly if folded in.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `backend/app/models/goal.py` | `Goal`, `GoalAccount`, `GoalKind`, `GoalStatus` |
| `backend/migrations/versions/f4a29c7d1e63_goals.py` | `goals` + `goal_accounts` tables, both enums |
| `backend/app/schemas/goal.py` | `GoalCreate`, `GoalUpdate`, `GoalOut` |
| `backend/app/schemas/forecast.py` | `ForecastDayOut`, `AffordIn`, `AffordOut`, `GoalAffordabilityOut` |
| `backend/app/services/goals.py` | CRUD, account linking, progress |
| `backend/app/services/forecast.py` | `project`, `can_i_afford`, `goal_projection`, `goals_overview` |
| `backend/app/api/goals.py` | `/goals` router |
| `backend/app/api/forecast.py` | `/forecast` router |
| `backend/tests/test_goals.py` | Service-level goals tests |
| `backend/tests/test_forecast.py` | Service-level forecast tests |
| `backend/tests/test_goals_api.py` | HTTP-level goals tests |
| `backend/tests/test_forecast_api.py` | HTTP-level forecast tests |
| `frontend/src/goals.ts` | Types + TanStack hooks + `goalPercent` |
| `frontend/src/goals.test.tsx` | Hook and pure-function tests |
| `frontend/src/forecast.ts` | Types + TanStack hooks + `firstNegativeDay` |
| `frontend/src/forecast.test.tsx` | Hook and pure-function tests |
| `frontend/src/GoalCards.tsx` | Goal list, progress rings, create/archive/delete |
| `frontend/src/GoalCards.test.tsx` | Component tests |
| `frontend/src/ForecastChart.tsx` | Overview forecast chart + "can I afford" input |
| `frontend/src/ForecastChart.test.tsx` | Component tests |
| `frontend/src/pages/GoalsPage.tsx` | Page shell |
| `frontend/e2e/goals.spec.ts` | End-to-end flow |

**Modify:**

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Register `Goal`, `GoalAccount` |
| `backend/app/main.py` | Include the `goals` and `forecast` routers |
| `backend/tests/test_tenancy.py` | Append a goals isolation case |
| `frontend/src/pages/OverviewPage.tsx` | Mount `ForecastChart` |
| `frontend/src/App.tsx` | `/goals` route |
| `frontend/src/ui/Shell.tsx` | Add "Goals" — see Task 14's two-branch instruction |
| `README.md` | Goals + forecast bullet |
| `CHANGELOG.md` | P3 entry |

---

### Task 1: The `Goal` and `GoalAccount` models, and the migration

**Files:**
- Create: `backend/app/models/goal.py`
- Create: `backend/migrations/versions/f4a29c7d1e63_goals.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_goals.py`

**Interfaces:**
- Consumes: `Base`/`UUIDMixin`/`TimestampMixin` from `app.models.base`.
- Produces:
  - `GoalKind` (`savings`, `debt_payoff`), `GoalStatus` (`active`, `achieved`, `archived`) — `str` enums.
  - `Goal` model: columns `id, household_id, name, kind, target_amount, target_date, monthly_funding, status, created_at`.
  - `GoalAccount` model: composite primary key `(goal_id, account_id)`, both `ON DELETE CASCADE`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_goals.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account import Account, AccountType
from app.models.goal import Goal, GoalAccount, GoalKind, GoalStatus
from app.models.household import Household


@pytest.fixture
def household(db):
    row = Household(name="Goals Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id,
        type=AccountType.savings,
        name="Emergency Fund",
        currency="USD",
        balance=Decimal("1200.00"),
    )
    db.add(row)
    db.commit()
    return row


def test_goal_row_can_be_created(db, household):
    row = Goal(
        household_id=household.id,
        name="Emergency Fund",
        kind=GoalKind.savings,
        target_amount=Decimal("10000.00"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.id is not None
    assert row.target_amount == Decimal("10000.0000")
    assert row.status == GoalStatus.active
    assert row.target_date is None
    assert row.monthly_funding is None


def test_goal_account_links_a_goal_to_an_account(db, household, account):
    goal = Goal(
        household_id=household.id, name="Fund", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    db.add(goal)
    db.commit()
    db.add(GoalAccount(goal_id=goal.id, account_id=account.id))
    db.commit()
    linked = db.scalar(select(GoalAccount).where(GoalAccount.goal_id == goal.id))
    assert linked.account_id == account.id


def test_deleting_a_goal_cascades_its_account_links(db, household, account):
    goal = Goal(
        household_id=household.id, name="Fund", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    db.add(goal)
    db.commit()
    db.add(GoalAccount(goal_id=goal.id, account_id=account.id))
    db.commit()
    db.delete(goal)
    db.commit()
    assert db.scalar(select(GoalAccount).where(GoalAccount.account_id == account.id)) is None


def test_deleting_an_account_cascades_its_goal_links(db, household, account):
    goal = Goal(
        household_id=household.id, name="Fund", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    db.add(goal)
    db.commit()
    db.add(GoalAccount(goal_id=goal.id, account_id=account.id))
    db.commit()
    db.delete(account)
    db.commit()
    assert db.scalar(select(GoalAccount).where(GoalAccount.goal_id == goal.id)) is None


def test_target_date_and_monthly_funding_are_optional(db, household):
    row = Goal(
        household_id=household.id,
        name="Car Payoff",
        kind=GoalKind.debt_payoff,
        target_amount=Decimal("8000.00"),
        target_date=date(2027, 6, 1),
        monthly_funding=Decimal("300.00"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.target_date == date(2027, 6, 1)
    assert row.monthly_funding == Decimal("300.0000")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.goal'`.

- [ ] **Step 3: Write the model**

Create `backend/app/models/goal.py`:

```python
import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class GoalKind(str, enum.Enum):
    savings = "savings"
    debt_payoff = "debt_payoff"


class GoalStatus(str, enum.Enum):
    active = "active"
    achieved = "achieved"
    archived = "archived"


class Goal(Base, UUIDMixin, TimestampMixin):
    """A savings target or a debt to pay off.

    Progress is never stored here — it's always the summed *current* balance of the
    accounts in `goal_accounts`, computed at read time in
    `services/goals.py::progress_for`. There is deliberately no contributions ledger:
    a running total of "money put toward this goal" that can drift from what the
    linked account's real balance says is a bug factory, not a feature.
    """

    __tablename__ = "goals"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    name: Mapped[str] = mapped_column()
    kind: Mapped[GoalKind] = mapped_column(Enum(GoalKind, name="goal_kind"))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Null means "use the forecast's own projected surplus" — see
    # services/forecast.py::goal_projection.
    monthly_funding: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, name="goal_status"), default=GoalStatus.active
    )


class GoalAccount(Base):
    """Which balances count toward a goal.

    A pure link row — no id, no timestamp, because it carries no information beyond
    the pair itself. Both sides cascade: delete the goal or the account and the link
    disappears with it (ON DELETE CASCADE at the schema level, not a manual purge in
    services/goals.py — a link row has no meaning once either end of it is gone).
    """

    __tablename__ = "goal_accounts"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
```

Add to `backend/app/models/__init__.py`, keeping the existing alphabetical order:

```python
from app.models.goal import Goal, GoalAccount, GoalKind, GoalStatus  # noqa: F401
```

placed after the `from app.models.connection import ...` line and before `from app.models.household import ...` (alphabetical by module name: `connection`, `goal`, `household`).

- [ ] **Step 4: Write the migration**

First, re-run the head check the STOP section above describes: `cd backend && .venv/Scripts/python -m alembic heads`. **If P2 has merged by now, the result will not be `e1f3a2c4b508` — use whatever the command actually reports as `down_revision` instead of the value below.** At the time this plan was written, with P2 unmerged, the real head was `e1f3a2c4b508`.

Create `backend/migrations/versions/f4a29c7d1e63_goals.py`:

```python
"""goals: savings and debt-payoff targets, and which accounts count toward them

Revision ID: f4a29c7d1e63
Revises: e1f3a2c4b508
Create Date: 2026-08-01

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a29c7d1e63"
down_revision: Union[str, Sequence[str], None] = "e1f3a2c4b508"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the explicit .create() calls in upgrade() own these types, same
# pattern as b2c3d4e5f6a7 (recurring_series) — Postgres does not drop an enum with
# its table, so downgrade() has to drop these explicitly too.
goal_kind = postgresql.ENUM("savings", "debt_payoff", name="goal_kind", create_type=False)
goal_status = postgresql.ENUM(
    "active", "achieved", "archived", name="goal_status", create_type=False
)


def upgrade() -> None:
    goal_kind.create(op.get_bind(), checkfirst=True)
    goal_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", goal_kind, nullable=False),
        sa.Column("target_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("monthly_funding", sa.Numeric(19, 4), nullable=True),
        sa.Column("status", goal_status, nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goals_household_id"), "goals", ["household_id"])

    op.create_table(
        "goal_accounts",
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("goal_id", "account_id"),
    )


def downgrade() -> None:
    op.drop_table("goal_accounts")
    op.drop_index(op.f("ix_goals_household_id"), table_name="goals")
    op.drop_table("goals")
    goal_status.drop(op.get_bind(), checkfirst=True)
    goal_kind.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 6: Verify the migration round-trips**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_migrations.py -v`
Expected: PASS. Runs the real Alembic chain — upgrade to head, downgrade one step, upgrade again — against a throwaway container.

- [ ] **Step 7: Lint and type-check**

Run: `cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app`
Expected: clean (no new errors beyond the documented pre-existing baseline).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/goal.py backend/app/models/__init__.py \
        backend/migrations/versions/f4a29c7d1e63_goals.py \
        backend/tests/test_goals.py
git commit -m "feat: a goal row and the accounts that count toward it"
```

---

### Task 2: Goals CRUD service, with tenancy-checked account linking

**Files:**
- Create: `backend/app/schemas/goal.py`
- Create: `backend/app/services/goals.py`
- Test: `backend/tests/test_goals.py` (append)

**Interfaces:**
- Consumes: `Goal`, `GoalAccount`, `GoalKind`, `GoalStatus` (Task 1); `accounts.get` from `app.services.accounts` (already shipped).
- Produces:
  - `GoalCreate`, `GoalUpdate` (Pydantic schemas).
  - `class UnknownAccount(Exception)`, `class UnknownGoal(Exception)`.
  - `create(db, household_id, *, name, kind, target_amount, target_date=None, monthly_funding=None, account_ids=None) -> Goal`
  - `list_for(db, household_id) -> list[Goal]`
  - `get(db, household_id, goal_id) -> Goal | None`
  - `linked_account_ids(db, household_id, goal_id) -> list[uuid.UUID]`
  - `update(db, household_id, goal_id, data: GoalUpdate) -> Goal | None`
  - `delete(db, household_id, goal_id) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_goals.py`:

```python
import uuid

from app.schemas.goal import GoalUpdate
from app.services import goals


def test_create_creates_a_goal_with_no_linked_accounts(db, household):
    row = goals.create(
        db, household.id, name="Emergency Fund", kind=GoalKind.savings,
        target_amount=Decimal("5000.00"),
    )
    assert row.id is not None
    assert goals.linked_account_ids(db, household.id, row.id) == []


def test_create_links_the_given_accounts(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    assert goals.linked_account_ids(db, household.id, row.id) == [account.id]


def test_create_rejects_an_account_the_household_cannot_see(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = Account(household_id=other.id, type=AccountType.checking, name="Theirs")
    db.add(theirs)
    db.commit()
    with pytest.raises(goals.UnknownAccount):
        goals.create(
            db, household.id, name="Fund", kind=GoalKind.savings,
            target_amount=Decimal("100"), account_ids=[theirs.id],
        )


def test_list_for_only_returns_this_households_goals(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    goals.create(db, household.id, name="Mine", kind=GoalKind.savings, target_amount=Decimal("1"))
    goals.create(db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1"))
    assert {g.name for g in goals.list_for(db, household.id)} == {"Mine"}


def test_get_returns_none_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.get(db, household.id, theirs.id) is None


def test_update_changes_fields_and_replaces_linked_accounts(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    other_account = Account(household_id=household.id, type=AccountType.checking, name="Other")
    db.add(other_account)
    db.commit()

    updated = goals.update(
        db, household.id, row.id, GoalUpdate(name="Renamed", account_ids=[other_account.id])
    )
    assert updated.name == "Renamed"
    assert goals.linked_account_ids(db, household.id, row.id) == [other_account.id]


def test_update_rejects_an_unknown_account(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    with pytest.raises(goals.UnknownAccount):
        goals.update(db, household.id, row.id, GoalUpdate(account_ids=[uuid.uuid4()]))


def test_update_returns_none_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.update(db, household.id, theirs.id, GoalUpdate(name="Hijacked")) is None


def test_update_leaves_account_links_alone_when_not_provided(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    goals.update(db, household.id, row.id, GoalUpdate(name="Renamed Only"))
    assert goals.linked_account_ids(db, household.id, row.id) == [account.id]


def test_delete_removes_the_goal_and_its_links(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    assert goals.delete(db, household.id, row.id) is True
    assert goals.get(db, household.id, row.id) is None


def test_delete_returns_false_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.delete(db, household.id, theirs.id) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.goals'`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/goal.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.goal import GoalKind, GoalStatus


class GoalCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(min_length=1, max_length=200)
    kind: GoalKind
    target_amount: Decimal = Field(gt=0)
    target_date: date | None = None
    monthly_funding: Decimal | None = Field(default=None, ge=0)
    account_ids: list[uuid.UUID] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: GoalKind | None = None
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_date: date | None = None
    monthly_funding: Decimal | None = Field(default=None, ge=0)
    status: GoalStatus | None = None
    account_ids: list[uuid.UUID] | None = None
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/goals.py`:

```python
"""Savings and debt-payoff goals.

Progress is always the summed *current* balance of the accounts linked to a goal —
there is no separate contributions ledger. See models/goal.py for why.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.goal import Goal, GoalAccount, GoalKind
from app.schemas.goal import GoalUpdate
from app.services import accounts


class UnknownAccount(Exception):
    """A goal can only link an account this household can actually see."""


class UnknownGoal(Exception):
    """The requested goal does not exist, or belongs to another household."""


def _check_accounts(db: Session, household_id: uuid.UUID, account_ids: list[uuid.UUID]) -> None:
    for account_id in account_ids:
        if accounts.get(db, household_id, account_id) is None:
            raise UnknownAccount(str(account_id))


def list_for(db: Session, household_id: uuid.UUID) -> list[Goal]:
    return list(
        db.scalars(select(Goal).where(Goal.household_id == household_id).order_by(Goal.name))
    )


def get(db: Session, household_id: uuid.UUID, goal_id: uuid.UUID) -> Goal | None:
    return db.scalar(select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id))


def linked_account_ids(
    db: Session, household_id: uuid.UUID, goal_id: uuid.UUID
) -> list[uuid.UUID]:
    return list(
        db.scalars(select(GoalAccount.account_id).where(GoalAccount.goal_id == goal_id))
    )


def _set_accounts(
    db: Session, household_id: uuid.UUID, goal_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> None:
    """Replace the full set of linked accounts. Validates every id against the
    household before anything is written — an unknown or foreign account id is a 422
    at the router, never a 500 from a foreign-key violation."""
    _check_accounts(db, household_id, account_ids)
    db.query(GoalAccount).filter(GoalAccount.goal_id == goal_id).delete()
    for account_id in account_ids:
        db.add(GoalAccount(goal_id=goal_id, account_id=account_id))


def create(
    db: Session,
    household_id: uuid.UUID,
    *,
    name: str,
    kind: GoalKind,
    target_amount: Decimal,
    target_date=None,
    monthly_funding: Decimal | None = None,
    account_ids: list[uuid.UUID] | None = None,
) -> Goal:
    account_ids = account_ids or []
    _check_accounts(db, household_id, account_ids)
    row = Goal(
        household_id=household_id,
        name=name,
        kind=kind,
        target_amount=target_amount,
        target_date=target_date,
        monthly_funding=monthly_funding,
    )
    db.add(row)
    db.flush()  # need row.id before the link rows can reference it
    for account_id in account_ids:
        db.add(GoalAccount(goal_id=row.id, account_id=account_id))
    db.commit()
    db.refresh(row)
    return row


def update(db: Session, household_id: uuid.UUID, goal_id: uuid.UUID, data: GoalUpdate) -> Goal | None:
    row = get(db, household_id, goal_id)
    if row is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    if "account_ids" in fields:
        _set_accounts(db, household_id, goal_id, fields.pop("account_ids"))
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, household_id: uuid.UUID, goal_id: uuid.UUID) -> bool:
    row = get(db, household_id, goal_id)
    if row is None:
        return False
    # goal_accounts rows disappear with it — ON DELETE CASCADE at the schema level,
    # not a manual purge; a link row has no meaning once the goal it links is gone.
    db.delete(row)
    db.commit()
    return True


def progress_for(db: Session, household_id: uuid.UUID, goal: Goal) -> Decimal:
    """The summed current balance of the goal's linked accounts, sign-flipped for
    debt_payoff — where progress is how much of the original target_amount has been
    paid down, not the balance itself. No linked accounts means no data to report
    progress from, so both kinds read zero rather than debt_payoff spuriously
    reading "fully paid" from summing an empty list against target_amount."""
    account_ids = linked_account_ids(db, household_id, goal.id)
    if not account_ids:
        return Decimal("0")
    balances = list(db.scalars(select(Account.balance).where(Account.id.in_(account_ids))))
    if goal.kind == GoalKind.debt_payoff:
        owed = sum((abs(b) for b in balances), Decimal("0"))
        return goal.target_amount - owed
    return sum(balances, Decimal("0"))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals.py -v`
Expected: PASS — 15 tests.

- [ ] **Step 6: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/schemas/goal.py backend/app/services/goals.py backend/tests/test_goals.py
git commit -m "feat: goals CRUD, with account links checked against the household"
```

---

### Task 3: Goal progress — savings, debt payoff, and the no-linked-accounts edge case

**Files:**
- Test: `backend/tests/test_goals.py` (append)

`progress_for` was already written in Task 2 (it needs to exist before `update`'s docstring references make sense and before Task 7 calls it) — this task is purely about proving its two spec-mandated edge cases with dedicated tests, matching how P2 gave `rollover_carry`'s invariant its own task even though the function shipped earlier.

**Interfaces:**
- Consumes: `goals.progress_for`, `goals.create` (Task 2).
- Produces: nothing new — test coverage only.

- [ ] **Step 1: Write the tests**

Append to `backend/tests/test_goals.py`:

```python
def test_progress_for_savings_is_the_summed_linked_balance(db, household):
    a1 = Account(household_id=household.id, type=AccountType.savings, name="A1", balance=Decimal("300.00"))
    a2 = Account(household_id=household.id, type=AccountType.checking, name="A2", balance=Decimal("150.00"))
    db.add_all([a1, a2])
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000"), account_ids=[a1.id, a2.id],
    )
    assert goals.progress_for(db, household.id, goal) == Decimal("450.00")


def test_progress_for_debt_payoff_is_the_amount_paid_down_from_target(db, household):
    loan = Account(household_id=household.id, type=AccountType.loan, name="Car Loan", balance=Decimal("-7000.00"))
    db.add(loan)
    db.commit()
    goal = goals.create(
        db, household.id, name="Payoff", kind=GoalKind.debt_payoff,
        target_amount=Decimal("10000.00"), account_ids=[loan.id],
    )
    # target_amount is read as the original 10000.00 owed; 7000.00 remains, so
    # 3000.00 has been paid down.
    assert goals.progress_for(db, household.id, goal) == Decimal("3000.00")


def test_progress_for_debt_payoff_handles_a_positive_stored_balance_too(db, household):
    # Some providers store a liability balance as a positive "amount owed" rather
    # than a negative one — progress_for takes the absolute value either way, the
    # same defensive stance services/snapshots.py already takes for net worth.
    loan = Account(household_id=household.id, type=AccountType.loan, name="Car Loan", balance=Decimal("7000.00"))
    db.add(loan)
    db.commit()
    goal = goals.create(
        db, household.id, name="Payoff", kind=GoalKind.debt_payoff,
        target_amount=Decimal("10000.00"), account_ids=[loan.id],
    )
    assert goals.progress_for(db, household.id, goal) == Decimal("3000.00")


def test_progress_for_a_goal_with_no_linked_accounts_is_zero_for_either_kind(db, household):
    savings_goal = goals.create(db, household.id, name="S", kind=GoalKind.savings, target_amount=Decimal("500"))
    debt_goal = goals.create(db, household.id, name="D", kind=GoalKind.debt_payoff, target_amount=Decimal("500"))
    assert goals.progress_for(db, household.id, savings_goal) == Decimal("0")
    assert goals.progress_for(db, household.id, debt_goal) == Decimal("0")
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals.py -v`
Expected: PASS — 19 tests. (These pass immediately since `progress_for` was written in Task 2; this step is confirming the two spec-mandated edge cases hold, not writing new implementation.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_goals.py
git commit -m "test: goal progress direction for debt payoff, and the no-accounts edge case"
```

---

### Task 4: `services/forecast.py` — the cadence walk

**Files:**
- Create: `backend/app/services/forecast.py`
- Test: `backend/tests/test_forecast.py`

This task does **not** touch `budgets` — see the STOP section. It builds steps 1, 2, 4, and 5 of `project()` (starting cash balance, recurring-cadence walk, hypotheticals, explainable contributions); step 3 (discretionary spend) is Task 5.

**Interfaces:**
- Consumes: `Account`, `AccountType` from `app.models.account`; `Cadence`, `RecurringSeries`, `SeriesStatus` from `app.models.recurring`; `recurring.list_for` from `app.services.recurring` (already shipped).
- Produces:
  - `CASH_ACCOUNT_TYPES: set[AccountType]`
  - `@dataclass Hypothetical: amount: Decimal; on_date: date; label: str = "Hypothetical"`
  - `@dataclass ForecastDay: on: date; projected_balance: Decimal; contributions: list[str]`
  - `project(db, household_id, months, hypotheticals=None, *, today=None) -> list[ForecastDay]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_forecast.py`:

```python
"""services/forecast.py — the cadence walk (Task 4), discretionary spend (Task 5),
can_i_afford (Task 6), and goal_projection/goals_overview (Task 7).

Task 4's tests below do not create a Budget row and do not import app.services.budgets
— see the STOP section at the top of this plan for why that boundary matters.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.services import forecast


@pytest.fixture
def household(db):
    row = Household(name="Forecast Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        currency="USD", balance=Decimal("1200.00"),
    )
    db.add(row)
    db.commit()
    return row


def _series(
    db, household, account, *, cadence, next_expected_on, typical_amount, direction,
    label="Test Series", status=SeriesStatus.active,
) -> RecurringSeries:
    row = RecurringSeries(
        household_id=household.id,
        account_id=account.id,
        merchant_key=label.lower(),
        label=label,
        cadence=cadence,
        status=status,
        direction=direction,
        typical_amount=typical_amount,
        last_amount=typical_amount,
        min_amount=typical_amount,
        max_amount=typical_amount,
        charge_count=3,
        first_charged_on=next_expected_on,
        last_charged_on=next_expected_on,
        next_expected_on=next_expected_on,
        confidence=90,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_forecast_with_zero_recurring_series_is_a_flat_line_at_the_cash_balance(db, household, account):
    days = forecast.project(db, household.id, months=3, today=date(2026, 7, 1))
    assert days
    assert all(d.projected_balance == account.balance for d in days)
    assert all(d.contributions == [] for d in days)


def test_cash_balance_excludes_non_cash_account_types(db, household, account):
    investment = Account(
        household_id=household.id, type=AccountType.investment, name="Brokerage",
        balance=Decimal("50000.00"),
    )
    db.add(investment)
    db.commit()
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    # Only the checking balance counts — the investment mark is not spendable cash.
    assert days[0].projected_balance == Decimal("1200.00")


def test_monthly_cadence_clamps_at_month_end_and_does_not_recover_the_31st(db, household, account):
    # 2026 is not a leap year: Jan 31 -> Feb 28 (clamped) -> Mar 28 (clamped cursor
    # never returns to the 31st once it's dropped to 28 — the same behavior
    # recurring.py's own _add_months already has, deliberately mirrored here).
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 1, 31), typical_amount=Decimal("50.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=3, today=date(2026, 1, 15))
    hits = [d.on for d in days if d.contributions]
    assert hits == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 28)]


def test_monthly_cadence_lands_on_a_real_leap_day(db, household, account):
    # 2028 is a leap year: Jan 31 -> Feb 29 (the actual leap day, not clamped to 28).
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2028, 1, 31), typical_amount=Decimal("50.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=2, today=date(2028, 1, 15))
    hits = [d.on for d in days if d.contributions]
    assert date(2028, 2, 29) in hits


def test_biweekly_cadence_drifts_across_a_calendar_year(db, household, account):
    start = date(2026, 1, 1)
    _series(
        db, household, account, cadence=Cadence.biweekly,
        next_expected_on=start, typical_amount=Decimal("100.00"), direction=1,
    )
    days = forecast.project(db, household.id, months=12, today=start)
    occurrence_days = [d.on for d in days if d.contributions]
    # 14 days doesn't divide the ~365-day span evenly: a year produces 27
    # occurrences, not the 26 a naive 365/14 estimate suggests — that gap is the
    # "drift" the spec's test list names explicitly.
    assert len(occurrence_days) == 27
    assert occurrence_days[0] == start
    assert occurrence_days[-1] == start + timedelta(days=14 * 26)
    assert all((d - start).days % 14 == 0 for d in occurrence_days)


def test_a_series_whose_next_expected_on_is_in_the_past_is_fast_forwarded(db, household, account):
    # Detection can stop running for a while; next_expected_on can be stale by the
    # time a forecast is requested. Walking from the stale date would replay months
    # of phantom missed charges — the walk starts from the first occurrence today
    # or later instead.
    stale = date(2025, 1, 1)
    today = date(2026, 7, 1)
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=stale, typical_amount=Decimal("15.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=1, today=today)
    occurrence_days = [d.on for d in days if d.contributions]
    assert occurrence_days
    assert occurrence_days[0] >= today
    assert occurrence_days[0].day == 1  # monthly cadence anchored on the 1st


def test_an_ended_series_is_not_walked(db, household, account):
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("15.00"), direction=-1,
        status=SeriesStatus.ended,
    )
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    assert all(d.contributions == [] for d in days)


def test_direction_and_typical_amount_move_the_balance_correctly(db, household, account):
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("1000.00"), direction=1,
        label="Paycheck",
    )
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    payday = next(d for d in days if d.on == date(2026, 7, 1))
    assert payday.projected_balance == Decimal("2200.00")  # 1200 starting + 1000 in
    assert payday.contributions == ["Paycheck +1000.00"]


def test_a_hypothetical_applies_on_its_exact_date_and_nowhere_else(db, household, account):
    hyp = forecast.Hypothetical(amount=Decimal("-500.00"), on_date=date(2026, 7, 10), label="New couch")
    days = forecast.project(db, household.id, months=1, hypotheticals=[hyp], today=date(2026, 7, 1))
    before = next(d for d in days if d.on == date(2026, 7, 9))
    on_day = next(d for d in days if d.on == date(2026, 7, 10))
    after = next(d for d in days if d.on == date(2026, 7, 11))
    assert before.projected_balance == Decimal("1200.00")
    assert on_day.projected_balance == Decimal("700.00")
    assert after.projected_balance == Decimal("700.00")
    assert on_day.contributions == ["New couch -500.00"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.forecast'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/forecast.py`:

```python
"""Cash-flow forecast: a daily walk from today's cash balances, applying recurring
cadences, budgeted discretionary spend, and any hypothetical the caller adds. Every
number traces to something real — a recurring series, a budget row, a hypothetical
typed in by hand — never a model's guess. No strategy engine, no simulation: the cut
list (avalanche/snowball, Monte Carlo, retirement projection) stays cut here.
"""

import uuid
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.services import recurring

# Balances a household can actually spend from. Net worth (services/snapshots.py,
# already shipped) already answers "what's my whole balance sheet" — this answers
# the narrower "how much spendable cash will I have," so investment/crypto marks and
# every liability/asset type are excluded on purpose. See Global Constraints
# deviation 6.
CASH_ACCOUNT_TYPES = {AccountType.checking, AccountType.savings, AccountType.cash}

_CADENCE_STEP_DAYS = {Cadence.weekly: 7, Cadence.biweekly: 14}
_CADENCE_STEP_MONTHS = {Cadence.monthly: 1, Cadence.quarterly: 3, Cadence.yearly: 12}


def _add_months(d: date, months: int) -> date:
    """Deliberately duplicates recurring.py's own private `_add_months` rather than
    importing a leading-underscore name across modules — same clamping logic (the
    31st in a 30-day month becomes the 30th, and once a cursor clamps it never
    un-clamps), proven already by recurring.py's own detection tests."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _step_forward(d: date, cadence: Cadence) -> date:
    step_days = _CADENCE_STEP_DAYS.get(cadence)
    if step_days is not None:
        return d + timedelta(days=step_days)
    return _add_months(d, _CADENCE_STEP_MONTHS[cadence])


def _first_occurrence_on_or_after(series: RecurringSeries, today: date) -> date | None:
    """A series' next_expected_on can be in the past — nothing rewinds it once
    detection stops running. Fast-forward to the first occurrence today or later
    before the walk starts, rather than replaying every missed occurrence."""
    if series.next_expected_on is None:
        return None
    cursor = series.next_expected_on
    guard = 0
    while cursor < today:
        cursor = _step_forward(cursor, series.cadence)
        guard += 1
        if guard > 10_000:  # a corrupt row; never loop forever over bad data
            return None
    return cursor


def _cash_balance(db: Session, household_id: uuid.UUID) -> Decimal:
    rows = db.scalars(
        select(Account.balance).where(
            Account.household_id == household_id, Account.type.in_(CASH_ACCOUNT_TYPES)
        )
    )
    return sum(rows, Decimal("0"))


@dataclass
class Hypothetical:
    amount: Decimal  # negative for an outflow, positive for an inflow
    on_date: date
    label: str = "Hypothetical"


@dataclass
class ForecastDay:
    on: date
    projected_balance: Decimal
    contributions: list[str] = field(default_factory=list)


def project(
    db: Session,
    household_id: uuid.UUID,
    months: int,
    hypotheticals: list[Hypothetical] | None = None,
    *,
    today: date | None = None,
) -> list[ForecastDay]:
    """A daily balance series from today's cash balances through `months` months out.

    1. Starts at today's summed cash-account balances.
    2. Walks forward day by day, applying every active RecurringSeries whose cadence
       lands on that day.
    3. Discretionary spend is zero here — Task 5 wires in the real budgeted-spend
       computation; until then the walk only reflects recurring cadences and
       whatever hypotheticals are passed in.
    4. Applies any hypothetical outflows/inflows on their exact date.
    5. Every day's `contributions` names what moved it, so any point on the
       resulting chart is explainable back to a real row.
    """
    today = today or date.today()
    end = _add_months(today, months)
    hypotheticals = hypotheticals or []

    balance = _cash_balance(db, household_id)
    active_series = recurring.list_for(db, household_id, status=SeriesStatus.active)
    cursors = {
        s.id: _first_occurrence_on_or_after(s, today)
        for s in active_series
        if s.next_expected_on is not None
    }

    daily_discretionary = Decimal("0")

    by_date: dict[date, list[Hypothetical]] = {}
    for h in hypotheticals:
        by_date.setdefault(h.on_date, []).append(h)

    out: list[ForecastDay] = []
    d = today
    while d <= end:
        contributions: list[str] = []

        for s in active_series:
            cursor = cursors.get(s.id)
            if cursor is None:
                continue
            while cursor == d:
                signed = s.typical_amount * s.direction
                balance += signed
                contributions.append(f"{s.label} {signed:+.2f}")
                cursor = _step_forward(cursor, s.cadence)
                cursors[s.id] = cursor

        if daily_discretionary:
            balance -= daily_discretionary
            contributions.append(f"Discretionary spend -{daily_discretionary:.2f}")

        for h in by_date.get(d, []):
            balance += h.amount
            contributions.append(f"{h.label} {h.amount:+.2f}")

        out.append(ForecastDay(on=d, projected_balance=balance, contributions=contributions))
        d += timedelta(days=1)

    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/forecast.py backend/tests/test_forecast.py
git commit -m "feat: walk recurring cadences forward from today's cash balance"
```

---

### Task 5: Discretionary spend — the current month's uncovered budget, spread evenly

**Files:**
- Modify: `backend/app/services/forecast.py`
- Test: `backend/tests/test_forecast.py` (append)

**Re-run the STOP-section verification before starting this task.** `ls backend/app/models/budget.py` must exist and `.venv/Scripts/python -m alembic heads` must include P2's migration. If not, stop here — do not stub this out.

**Interfaces:**
- Consumes: `budgets.status`, `budgets.BudgetItem` from `app.services.budgets` (P2); `recurring.charges` from `app.services.recurring` (already shipped).
- Produces: `project()` (Task 4) now computes a real `daily_discretionary` instead of a hardcoded zero.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_forecast.py`:

```python
from app.models.transaction import Transaction
from app.services import budgets
from app.services.categories import ensure_system_categories, system_category_id


def test_discretionary_spend_is_the_current_months_uncovered_budget_spread_evenly(db, household, account):
    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    streaming = system_category_id("Bills & Utilities/Streaming")
    today = date(2026, 7, 1)  # July has 31 days

    budgets.upsert(
        db, household.id, today,
        [
            budgets.BudgetItem(groceries, Decimal("310.00")),
            budgets.BudgetItem(streaming, Decimal("15.00")),
        ],
    )

    # A recurring series whose actual charge landed in Streaming — its budget should
    # be treated as already accounted for by the recurring line, not double-counted
    # as discretionary spend too.
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 8, 1), typical_amount=Decimal("15.00"), direction=-1,
        label="Streamer",
    )
    db.add(
        Transaction(
            household_id=household.id, account_id=account.id,
            posted_at=datetime(2026, 6, 15, tzinfo=UTC), amount=Decimal("-15.00"),
            merchant_raw="Streamer", category_id=streaming,
        )
    )
    db.commit()

    days = forecast.project(db, household.id, months=1, today=today)
    discretionary_lines = [c for d in days for c in d.contributions if c.startswith("Discretionary")]
    # Only Groceries' 310.00 counts (Streaming is covered), spread over July's 31 days.
    daily = Decimal("310.00") / 31
    assert len(discretionary_lines) == len(days)  # applied every single day
    assert discretionary_lines[0] == f"Discretionary spend -{daily:.2f}"


def test_discretionary_spend_is_zero_with_no_budgets_at_all(db, household, account):
    ensure_system_categories(db)
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    assert all(d.contributions == [] for d in days)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: FAIL — the first new test's assertion on `discretionary_lines` fails because `daily_discretionary` is still hardcoded to zero.

- [ ] **Step 3: Implement**

In `backend/app/services/forecast.py`, add to the imports:

```python
from app.services import budgets
```

Add this helper, near `_cash_balance`:

```python
def _recurring_covered_categories(db: Session, household_id: uuid.UUID) -> set[uuid.UUID]:
    """Category ids already accounted for by an active recurring series, so this
    doesn't double-count a subscription as both a recurring line and discretionary
    spend. RecurringSeries carries no category of its own, so this is built from the
    transactions each series already matches — exactly as expensive as
    recurring.charges() already is anywhere else it's called."""
    covered: set[uuid.UUID] = set()
    for series in recurring.list_for(db, household_id, status=SeriesStatus.active):
        for txn in recurring.charges(db, household_id, series):
            if txn.category_id is not None:
                covered.add(txn.category_id)
    return covered
```

In `project()`, replace:

```python
    daily_discretionary = Decimal("0")
```

with:

```python
    # The current month's budgeted total for categories no recurring series already
    # covers, spread over that month's day count — held constant for the whole
    # horizon. See Global Constraints deviation 5 for why this isn't recomputed
    # per future calendar month.
    covered = _recurring_covered_categories(db, household_id)
    month_start = today.replace(day=1)
    days_in_month = monthrange(today.year, today.month)[1]
    discretionary_total = sum(
        (
            row.budgeted
            for row in budgets.status(db, household_id, month_start)
            if row.category_id not in covered
        ),
        Decimal("0"),
    )
    daily_discretionary = (
        discretionary_total / days_in_month if discretionary_total else Decimal("0")
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: PASS — 11 tests. Also re-run Task 4's tests to confirm no regression: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py::test_forecast_with_zero_recurring_series_is_a_flat_line_at_the_cash_balance -v` (an empty taxonomy means `budgets.status` returns `[]`, so `discretionary_total` stays zero and that test's flat-line assertion still holds).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/forecast.py backend/tests/test_forecast.py
git commit -m "feat: spread the current month's uncovered budget into the forecast"
```

---

### Task 6: `can_i_afford` — the hypothetical, doubled

**Files:**
- Modify: `backend/app/services/forecast.py`
- Test: `backend/tests/test_forecast.py` (append)

**Interfaces:**
- Consumes: `project`, `Hypothetical` (Task 4); `goals.list_for`, `goals.progress_for` (Task 2); `GoalStatus` from `app.models.goal`.
- Produces:
  - `@dataclass GoalAffordability: goal_id: uuid.UUID; goal_name: str; baseline_date: date | None; with_amount_date: date | None`
  - `@dataclass AffordabilityResult: baseline: list[ForecastDay]; with_amount: list[ForecastDay]; stays_non_negative: bool; minimum_balance: Decimal; goal_impact: list[GoalAffordability]`
  - `can_i_afford(db, household_id, amount, on_date, months, *, today=None) -> AffordabilityResult`
  - `_goal_date_from_series(db, household_id, goal, series, today) -> date | None` (module-private; Task 7 reuses it)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_forecast.py`:

```python
from app.models.goal import GoalKind
from app.services import goals


def test_can_i_afford_an_amount_that_empties_the_account(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("1200.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    # Emptying the account to exactly zero is not an overdraft — see Global
    # Constraints deviation 4 for why this is >= 0, not > 0.
    assert result.stays_non_negative is True
    assert result.minimum_balance == Decimal("0.00")


def test_can_i_afford_an_amount_larger_than_the_balance_goes_negative(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("1500.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert result.stays_non_negative is False
    assert result.minimum_balance < 0


def test_can_i_afford_returns_both_a_baseline_and_a_with_amount_series(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert len(result.baseline) == len(result.with_amount)
    baseline_day5 = next(d for d in result.baseline if d.on == date(2026, 7, 5))
    with_day5 = next(d for d in result.with_amount if d.on == date(2026, 7, 5))
    assert with_day5.projected_balance == baseline_day5.projected_balance - Decimal("100.00")


def test_can_i_afford_reports_impact_on_each_active_goal(db, household, account):
    goal = goals.create(
        db, household.id, name="Vacation", kind=GoalKind.savings,
        target_amount=Decimal("5000.00"), account_ids=[account.id],
    )
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=12, today=date(2026, 7, 1)
    )
    impact = next(g for g in result.goal_impact if g.goal_id == goal.id)
    assert impact.goal_name == "Vacation"


def test_can_i_afford_ignores_archived_goals(db, household, account):
    from app.schemas.goal import GoalUpdate

    goal = goals.create(
        db, household.id, name="Old Goal", kind=GoalKind.savings,
        target_amount=Decimal("100.00"), account_ids=[account.id],
    )
    goals.update(db, household.id, goal.id, GoalUpdate(status="archived"))
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert all(g.goal_id != goal.id for g in result.goal_impact)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: FAIL — `AttributeError: module 'app.services.forecast' has no attribute 'can_i_afford'`.

- [ ] **Step 3: Implement**

Add to the imports in `backend/app/services/forecast.py`:

```python
import math

from app.models.goal import Goal, GoalStatus
from app.services import goals
```

Append:

```python
def _goal_date_from_series(
    db: Session,
    household_id: uuid.UUID,
    goal: Goal,
    series: list[ForecastDay],
    today: date,
) -> date | None:
    """The date `goal` is reached, given a computed forecast `series` for the
    "use the forecast's surplus" case, or a fixed monthly_funding rate for the case
    the user typed one in by hand. Shared by can_i_afford (comparing baseline vs.
    with-amount) and goal_projection (Task 7)."""
    progress = goals.progress_for(db, household_id, goal)
    remaining = goal.target_amount - progress
    if remaining <= 0:
        return today  # already met

    if goal.monthly_funding:
        # A funding rate the user typed in is a monthly commitment, not a slice of
        # the household's whole cash flow — walk in fixed monthly increments rather
        # than the daily series.
        cursor = today
        remaining_after = remaining
        guard = 0
        while remaining_after > 0:
            cursor = _add_months(cursor, 1)
            remaining_after -= goal.monthly_funding
            guard += 1
            if guard > 1200:  # 100 years; a funding rate too small to ever finish
                return None
        return cursor

    if len(series) < 2:
        return None
    delta = series[-1].projected_balance - series[0].projected_balance
    if delta <= 0:
        return None
    total_days = (series[-1].on - series[0].on).days
    daily_rate = delta / Decimal(total_days)
    days_needed = remaining / daily_rate
    return today + timedelta(days=math.ceil(days_needed))


@dataclass
class GoalAffordability:
    goal_id: uuid.UUID
    goal_name: str
    baseline_date: date | None
    with_amount_date: date | None


@dataclass
class AffordabilityResult:
    baseline: list[ForecastDay]
    with_amount: list[ForecastDay]
    stays_non_negative: bool
    minimum_balance: Decimal
    goal_impact: list[GoalAffordability]


def can_i_afford(
    db: Session,
    household_id: uuid.UUID,
    amount: Decimal,
    on_date: date,
    months: int,
    *,
    today: date | None = None,
) -> AffordabilityResult:
    """Runs project() twice — with and without the hypothetical outflow — so every
    number on the "can I afford this" screen traces to the same walk the forecast
    chart already draws, rather than a separate estimate."""
    today = today or date.today()
    baseline = project(db, household_id, months, today=today)
    outflow = Hypothetical(amount=-abs(amount), on_date=on_date, label="Hypothetical purchase")
    with_amount = project(db, household_id, months, [outflow], today=today)

    minimum_balance = min(
        (day.projected_balance for day in with_amount), default=Decimal("0")
    )
    stays_non_negative = minimum_balance >= 0

    goal_impact = [
        GoalAffordability(
            goal_id=g.id,
            goal_name=g.name,
            baseline_date=_goal_date_from_series(db, household_id, g, baseline, today),
            with_amount_date=_goal_date_from_series(db, household_id, g, with_amount, today),
        )
        for g in goals.list_for(db, household_id)
        if g.status == GoalStatus.active
    ]

    return AffordabilityResult(
        baseline=baseline,
        with_amount=with_amount,
        stays_non_negative=stays_non_negative,
        minimum_balance=minimum_balance,
        goal_impact=goal_impact,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: PASS — 16 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/forecast.py backend/tests/test_forecast.py
git commit -m "feat: can_i_afford runs the forecast twice and says what it costs each goal"
```

---

### Task 7: `goal_projection` and `goals_overview`

**Files:**
- Modify: `backend/app/services/forecast.py`
- Test: `backend/tests/test_forecast.py` (append)

**Interfaces:**
- Consumes: `project`, `_goal_date_from_series` (Task 6); `goals.get`, `goals.list_for`, `goals.progress_for` (Task 2).
- Produces:
  - `class UnknownGoal(Exception)`
  - `goal_projection(db, household_id, goal_id, *, months=12, today=None) -> date | None` — raises `UnknownGoal`
  - `@dataclass GoalOverview: goal_id: uuid.UUID; progress: Decimal; projected_date: date | None`
  - `goals_overview(db, household_id, *, months=12, today=None) -> list[GoalOverview]`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_forecast.py`:

```python
def test_goal_projection_uses_monthly_funding_when_set(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("200.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1200.00"), monthly_funding=Decimal("500.00"), account_ids=[acct.id],
    )
    projected = forecast.goal_projection(db, household.id, goal.id, today=date(2026, 7, 1))
    # remaining = 1200 - 200 = 1000; at 500/month that's 2 months -> Sep 1.
    assert projected == date(2026, 9, 1)


def test_goal_projection_uses_the_forecast_surplus_when_monthly_funding_is_null(db, household):
    acct = Account(household_id=household.id, type=AccountType.checking, name="Fund Acct", balance=Decimal("0.00"))
    db.add(acct)
    db.commit()
    # A steady 1000.00/month paycheck as the only cash flow gives the forecast a
    # known, checkable surplus rate to project the goal against.
    _series(
        db, household, acct, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("1000.00"), direction=1,
        label="Paycheck",
    )
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("3000.00"), account_ids=[acct.id],
    )
    projected = forecast.goal_projection(db, household.id, goal.id, months=12, today=date(2026, 7, 1))
    assert projected is not None


def test_goal_projection_raises_for_an_unknown_goal(db, household):
    with pytest.raises(forecast.UnknownGoal):
        forecast.goal_projection(db, household.id, uuid.uuid4())


def test_goal_projection_is_today_when_the_target_is_already_met(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("5000.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000.00"), account_ids=[acct.id],
    )
    assert forecast.goal_projection(db, household.id, goal.id, today=date(2026, 7, 1)) == date(2026, 7, 1)


def test_goals_overview_pairs_progress_with_projected_date_for_every_goal(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("500.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000.00"), monthly_funding=Decimal("250.00"), account_ids=[acct.id],
    )
    overview = forecast.goals_overview(db, household.id, today=date(2026, 7, 1))
    row = next(o for o in overview if o.goal_id == goal.id)
    assert row.progress == Decimal("500.00")
    assert row.projected_date == date(2026, 9, 1)  # remaining 500 / 250 per month = 2 months
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast.py -v`
Expected: FAIL — `AttributeError: module 'app.services.forecast' has no attribute 'goal_projection'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/forecast.py`:

```python
class UnknownGoal(Exception):
    """The requested goal does not exist, or belongs to another household."""


def goal_projection(
    db: Session,
    household_id: uuid.UUID,
    goal_id: uuid.UUID,
    *,
    months: int = 12,
    today: date | None = None,
) -> date | None:
    """The date `goal_id` is reached at current funding — the forecast's own
    surplus when monthly_funding is null, per the spec."""
    goal = goals.get(db, household_id, goal_id)
    if goal is None:
        raise UnknownGoal(str(goal_id))
    today = today or date.today()
    series = project(db, household_id, months, today=today)
    return _goal_date_from_series(db, household_id, goal, series, today)


@dataclass
class GoalOverview:
    goal_id: uuid.UUID
    progress: Decimal
    projected_date: date | None


def goals_overview(
    db: Session, household_id: uuid.UUID, *, months: int = 12, today: date | None = None
) -> list[GoalOverview]:
    """Progress and a projected completion date for every goal, computed from one
    shared project() call rather than one per goal — the walk is identical
    regardless of which goal is asking."""
    today = today or date.today()
    series = project(db, household_id, months, today=today)
    return [
        GoalOverview(
            goal_id=g.id,
            progress=goals.progress_for(db, household_id, g),
            projected_date=_goal_date_from_series(db, household_id, g, series, today),
        )
        for g in goals.list_for(db, household_id)
    ]
```

- [ ] **Step 4: Run the whole backend suite, lint, type-check**

Run: `cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app`
Expected: PASS. This is the point where `services/forecast.py` and `services/goals.py` are both complete — a full-suite run catches any interaction the per-file runs above missed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/forecast.py backend/tests/test_forecast.py
git commit -m "feat: a projected date for every goal, from monthly_funding or the forecast surplus"
```

---

### Task 8: Pydantic schemas for the API layer

**Files:**
- Modify: `backend/app/schemas/goal.py`
- Create: `backend/app/schemas/forecast.py`

No test of its own — exercised by Tasks 9–10, same reasoning P2 gave its own schema-only task.

**Interfaces:**
- Consumes: `Goal`, `GoalKind`, `GoalStatus` (Task 1); `ForecastDay`, `GoalAffordability` (Tasks 4, 6).
- Produces: `GoalOut` (append to `schemas/goal.py`); `ForecastDayOut`, `AffordIn`, `GoalAffordabilityOut`, `AffordOut` (`schemas/forecast.py`).

- [ ] **Step 1: Append `GoalOut`**

Append to `backend/app/schemas/goal.py`:

```python
class GoalOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: GoalKind
    target_amount: Decimal
    target_date: date | None
    monthly_funding: Decimal | None
    status: GoalStatus
    account_ids: list[uuid.UUID]
    progress: Decimal
    projected_date: date | None
```

`GoalOut` has no `model_config = {"from_attributes": True}` — unlike `CategoryOut`/`BudgetOut`, it is never built directly from a `Goal` ORM row (which has no `account_ids`, `progress`, or `projected_date` columns). The router (Task 9) always constructs it field by field from a `Goal` row plus a `GoalOverview`.

- [ ] **Step 2: Write the forecast schemas**

Create `backend/app/schemas/forecast.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ForecastDayOut(BaseModel):
    on: date
    projected_balance: Decimal
    contributions: list[str]


class AffordIn(BaseModel):
    amount: Decimal = Field(gt=0)
    on_date: date
    months: int = Field(default=6, ge=1, le=60)


class GoalAffordabilityOut(BaseModel):
    goal_id: uuid.UUID
    goal_name: str
    baseline_date: date | None
    with_amount_date: date | None


class AffordOut(BaseModel):
    baseline: list[ForecastDayOut]
    with_amount: list[ForecastDayOut]
    stays_non_negative: bool
    minimum_balance: Decimal
    goal_impact: list[GoalAffordabilityOut]
```

- [ ] **Step 3: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/schemas/goal.py backend/app/schemas/forecast.py
git commit -m "feat: schemas for goals and the forecast API"
```

---

### Task 9: The `/goals` router

**Files:**
- Create: `backend/app/api/goals.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_goals_api.py`

**Interfaces:**
- Consumes: `goals.create/list_for/get/update/delete/linked_account_ids`, `goals.UnknownAccount` (Task 2); `forecast.goals_overview` (Task 7); `GoalCreate`, `GoalUpdate`, `GoalOut` (Task 8).
- Produces: Router `goals.router`, prefix `/goals`:
  - `GET /goals` -> `list[GoalOut]`
  - `POST /goals` -> `GoalOut`
  - `PATCH /goals/{goal_id}` -> `GoalOut`
  - `DELETE /goals/{goal_id}` -> `{"status": "ok"}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_goals_api.py`:

```python
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Goals API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.savings, name="Fund", balance=Decimal("400.00")
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_create_and_list_goal(client, account):
    res = client.post(
        "/goals",
        json={
            "name": "Emergency Fund", "kind": "savings", "target_amount": "1000.00",
            "account_ids": [str(account.id)],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Emergency Fund"
    assert Decimal(body["progress"]) == Decimal("400.00")

    listed = client.get("/goals").json()
    assert len(listed) == 1


def test_create_rejects_a_foreign_account_with_422_not_500(client):
    res = client.post(
        "/goals",
        json={"name": "Fund", "kind": "savings", "target_amount": "1", "account_ids": [str(uuid.uuid4())]},
    )
    assert res.status_code == 422


def test_patch_updates_fields(client, account):
    created = client.post(
        "/goals",
        json={
            "name": "Fund", "kind": "savings", "target_amount": "1000.00",
            "account_ids": [str(account.id)],
        },
    ).json()
    res = client.patch(f"/goals/{created['id']}", json={"name": "Renamed", "status": "archived"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    assert res.json()["status"] == "archived"


def test_patch_unknown_goal_is_404(client):
    assert client.patch(f"/goals/{uuid.uuid4()}", json={"name": "X"}).status_code == 404


def test_delete_goal(client, account):
    created = client.post(
        "/goals",
        json={"name": "Fund", "kind": "savings", "target_amount": "1", "account_ids": [str(account.id)]},
    ).json()
    assert client.delete(f"/goals/{created['id']}").status_code == 200
    assert client.get("/goals").json() == []


def test_delete_unknown_goal_is_404(client):
    assert client.delete(f"/goals/{uuid.uuid4()}").status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals_api.py -v`
Expected: FAIL — 404 on every `/goals` route.

- [ ] **Step 3: Write the router**

Create `backend/app/api/goals.py`:

```python
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.goal import Goal
from app.schemas.goal import GoalCreate, GoalOut, GoalUpdate
from app.services import forecast, goals

router = APIRouter(prefix="/goals", tags=["goals"])


def _out(
    db: Session,
    household_id: uuid.UUID,
    row: Goal,
    overview: dict[uuid.UUID, forecast.GoalOverview],
) -> GoalOut:
    o = overview.get(row.id)
    return GoalOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        target_amount=row.target_amount,
        target_date=row.target_date,
        monthly_funding=row.monthly_funding,
        status=row.status,
        account_ids=goals.linked_account_ids(db, household_id, row.id),
        progress=o.progress if o else Decimal("0"),
        projected_date=o.projected_date if o else None,
    )


@router.get("", response_model=list[GoalOut])
def list_goals(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[GoalOut]:
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return [_out(db, hid, row, overview) for row in goals.list_for(db, hid)]


@router.post("", response_model=GoalOut)
def create_goal(
    body: GoalCreate, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> GoalOut:
    try:
        row = goals.create(
            db, hid, name=body.name, kind=body.kind, target_amount=body.target_amount,
            target_date=body.target_date, monthly_funding=body.monthly_funding,
            account_ids=body.account_ids,
        )
    except goals.UnknownAccount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return _out(db, hid, row, overview)


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: uuid.UUID, body: GoalUpdate,
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db),
) -> GoalOut:
    try:
        row = goals.update(db, hid, goal_id, body)
    except goals.UnknownAccount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return _out(db, hid, row, overview)


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not goals.delete(db, hid, goal_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"status": "ok"}
```

In `backend/app/main.py`, add `goals` to the `from app.api import (...)` block (keep the list alphabetical) and `app.include_router(goals.router)` alongside the others.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_goals_api.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/api/goals.py backend/app/main.py backend/tests/test_goals_api.py
git commit -m "feat: goals over HTTP"
```

---

### Task 10: The `/forecast` router, plus the tenancy test

**Files:**
- Create: `backend/app/api/forecast.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_forecast_api.py`
- Test: `backend/tests/test_tenancy.py` (append)

**Interfaces:**
- Consumes: `forecast.project`, `forecast.can_i_afford` (Tasks 4, 6); `ForecastDayOut`, `AffordIn`, `AffordOut`, `GoalAffordabilityOut` (Task 8).
- Produces: Router `forecast.router`, prefix `/forecast`:
  - `GET /forecast?months=6` -> `list[ForecastDayOut]`
  - `POST /forecast/afford` -> `AffordOut`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_forecast_api.py`:

```python
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Forecast API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        balance=Decimal("1000.00"),
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_get_forecast_defaults_to_six_months(client, account):
    res = client.get("/forecast")
    assert res.status_code == 200
    body = res.json()
    assert body
    assert Decimal(body[0]["projected_balance"]) == Decimal("1000.00")


def test_get_forecast_rejects_an_out_of_range_months_with_422_not_500(client, account):
    assert client.get("/forecast?months=0").status_code == 422
    assert client.get("/forecast?months=61").status_code == 422


def test_afford_endpoint_returns_both_series_and_a_verdict(client, account):
    res = client.post(
        "/forecast/afford", json={"amount": "200.00", "on_date": "2026-07-05", "months": 1}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stays_non_negative"] is True
    assert len(body["baseline"]) == len(body["with_amount"])


def test_afford_endpoint_rejects_a_non_positive_amount_with_422(client, account):
    res = client.post(
        "/forecast/afford", json={"amount": "0", "on_date": "2026-07-05", "months": 1}
    )
    assert res.status_code == 422
```

Append to `backend/tests/test_tenancy.py`, following the shape already there:

```python
from decimal import Decimal

from app.models.account import Account, AccountType
from app.models.goal import GoalKind
from app.services import goals


def test_goals_isolated_by_household(db):
    h1, h2 = _household(db).id, _household(db).id
    a1 = Account(household_id=h1, type=AccountType.savings, name="A1", balance=Decimal("500.00"))
    db.add(a1)
    db.commit()
    goal = goals.create(
        db, h1, name="Fund", kind=GoalKind.savings, target_amount=Decimal("1000"), account_ids=[a1.id]
    )

    assert {g.name for g in goals.list_for(db, h1)} == {"Fund"}
    assert goals.list_for(db, h2) == []
    assert goals.get(db, h2, goal.id) is None
    try:
        goals.create(
            db, h2, name="Borrowed", kind=GoalKind.savings, target_amount=Decimal("1"),
            account_ids=[a1.id],
        )
    except goals.UnknownAccount:
        pass
    else:
        raise AssertionError("expected UnknownAccount")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast_api.py tests/test_tenancy.py -v`
Expected: FAIL — 404 on every `/forecast` route.

- [ ] **Step 3: Write the router**

Create `backend/app/api/forecast.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.forecast import AffordIn, AffordOut, ForecastDayOut, GoalAffordabilityOut
from app.services import forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])

_MAX_MONTHS = 60


def _day_out(day: forecast.ForecastDay) -> ForecastDayOut:
    return ForecastDayOut(
        on=day.on, projected_balance=day.projected_balance, contributions=day.contributions
    )


@router.get("", response_model=list[ForecastDayOut])
def get_forecast(
    months: int = 6, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[ForecastDayOut]:
    if not 1 <= months <= _MAX_MONTHS:
        raise HTTPException(
            status_code=422, detail=f"months must be between 1 and {_MAX_MONTHS}"
        )
    return [_day_out(d) for d in forecast.project(db, hid, months)]


@router.post("/afford", response_model=AffordOut)
def afford(
    body: AffordIn, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> AffordOut:
    result = forecast.can_i_afford(db, hid, body.amount, body.on_date, body.months)
    return AffordOut(
        baseline=[_day_out(d) for d in result.baseline],
        with_amount=[_day_out(d) for d in result.with_amount],
        stays_non_negative=result.stays_non_negative,
        minimum_balance=result.minimum_balance,
        goal_impact=[
            GoalAffordabilityOut(
                goal_id=g.goal_id, goal_name=g.goal_name,
                baseline_date=g.baseline_date, with_amount_date=g.with_amount_date,
            )
            for g in result.goal_impact
        ],
    )
```

In `backend/app/main.py`, add `forecast` to the `from app.api import (...)` block (alphabetical) and `app.include_router(forecast.router)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_forecast_api.py tests/test_tenancy.py -v`
Expected: PASS — 4 tests in `test_forecast_api.py`, and every `test_tenancy.py` case including the new one.

- [ ] **Step 5: Run the whole backend suite, lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/api/forecast.py backend/app/main.py \
        backend/tests/test_forecast_api.py backend/tests/test_tenancy.py
git commit -m "feat: the forecast and can-i-afford endpoints"
```

---

### Task 11: Frontend data layer — `goals.ts` and `forecast.ts`

**Files:**
- Create: `frontend/src/goals.ts`
- Create: `frontend/src/goals.test.tsx`
- Create: `frontend/src/forecast.ts`
- Create: `frontend/src/forecast.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` from `./api/client`.
- Produces:
  - `type Goal`, `type NewGoal`, `useGoals()`, `useCreateGoal()`, `useUpdateGoal(id)`, `useDeleteGoal()`, `goalPercent(goal): number`
  - `type ForecastDay`, `type GoalAffordability`, `type AffordResult`, `useForecast(months=6)`, `useAfford()`, `firstNegativeDay(days): ForecastDay | null`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/goals.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { goalPercent, useGoals } from "./goals";
import type { Goal } from "./goals";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

const goal = (over: Partial<Goal> = {}): Goal => ({
  id: "g1",
  name: "Fund",
  kind: "savings",
  target_amount: "1000.0000",
  target_date: null,
  monthly_funding: null,
  status: "active",
  account_ids: [],
  progress: "250.0000",
  projected_date: null,
  ...over,
});

describe("useGoals", () => {
  it("fetches the goal list", async () => {
    vi.mocked(apiFetch).mockResolvedValue([goal()]);
    const { result } = renderHook(() => useGoals(), { wrapper });
    await waitFor(() => expect(result.current.data?.[0].name).toBe("Fund"));
    expect(apiFetch).toHaveBeenCalledWith("/goals");
  });
});

describe("goalPercent", () => {
  it("is progress over target, as a percentage", () => {
    expect(goalPercent(goal({ progress: "250.0000", target_amount: "1000.0000" }))).toBe(25);
  });

  it("clamps below zero up to zero", () => {
    expect(goalPercent(goal({ progress: "-50.0000" }))).toBe(0);
  });

  it("clamps above 100 down to 100", () => {
    expect(goalPercent(goal({ progress: "1500.0000", target_amount: "1000.0000" }))).toBe(100);
  });

  it("is zero for a zero or negative target rather than dividing by it", () => {
    expect(goalPercent(goal({ target_amount: "0" }))).toBe(0);
  });
});
```

Create `frontend/src/forecast.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { firstNegativeDay } from "./forecast";
import type { ForecastDay } from "./forecast";

const day = (on: string, balance: string): ForecastDay => ({
  on, projected_balance: balance, contributions: [],
});

describe("firstNegativeDay", () => {
  it("finds the first day the balance drops below zero", () => {
    const days = [day("2026-07-01", "500.00"), day("2026-07-02", "-10.00"), day("2026-07-03", "-20.00")];
    expect(firstNegativeDay(days)?.on).toBe("2026-07-02");
  });

  it("is null when the balance never goes negative", () => {
    expect(firstNegativeDay([day("2026-07-01", "500.00")])).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test -- goals forecast`
Expected: FAIL — cannot resolve `./goals` / `./forecast`.

- [ ] **Step 3: Write the data layers**

Create `frontend/src/goals.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type GoalKind = "savings" | "debt_payoff";
export type GoalStatus = "active" | "achieved" | "archived";

export type Goal = {
  id: string;
  name: string;
  kind: GoalKind;
  target_amount: string;
  target_date: string | null;
  monthly_funding: string | null;
  status: GoalStatus;
  account_ids: string[];
  progress: string;
  projected_date: string | null;
};

export type NewGoal = {
  name: string;
  kind: GoalKind;
  target_amount: string;
  target_date?: string | null;
  monthly_funding?: string | null;
  account_ids: string[];
};

export type GoalPatch = Partial<NewGoal> & { status?: GoalStatus };

export function useGoals() {
  return useQuery({ queryKey: ["goals"], queryFn: () => apiFetch<Goal[]>("/goals") });
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goal: NewGoal) =>
      apiFetch<Goal>("/goals", { method: "POST", body: JSON.stringify(goal) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useUpdateGoal(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: GoalPatch) =>
      apiFetch<Goal>(`/goals/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/goals/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

/** Percentage for a progress ring, clamped to [0, 100] — a debt paid down past its
 * original target, or a savings goal that overshoots, still draws a full ring
 * rather than an SVG arc past a full circle. */
export function goalPercent(goal: Goal): number {
  const target = Number(goal.target_amount);
  if (target <= 0) return 0;
  const pct = (Number(goal.progress) / target) * 100;
  return Math.max(0, Math.min(100, pct));
}
```

Create `frontend/src/forecast.ts`:

```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type ForecastDay = { on: string; projected_balance: string; contributions: string[] };

export type GoalAffordability = {
  goal_id: string;
  goal_name: string;
  baseline_date: string | null;
  with_amount_date: string | null;
};

export type AffordResult = {
  baseline: ForecastDay[];
  with_amount: ForecastDay[];
  stays_non_negative: boolean;
  minimum_balance: string;
  goal_impact: GoalAffordability[];
};

export function useForecast(months = 6) {
  return useQuery({
    queryKey: ["forecast", months],
    queryFn: () => apiFetch<ForecastDay[]>(`/forecast?months=${months}`),
  });
}

export function useAfford() {
  return useMutation({
    mutationFn: (body: { amount: string; on_date: string; months: number }) =>
      apiFetch<AffordResult>("/forecast/afford", { method: "POST", body: JSON.stringify(body) }),
  });
}

/** First day the projected balance drops below zero, if any — what the Overview
 * chart's negative-balance marker points at. */
export function firstNegativeDay(days: ForecastDay[]): ForecastDay | null {
  return days.find((d) => Number(d.projected_balance) < 0) ?? null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- goals forecast`
Expected: PASS — 5 tests in `goals.test.tsx`, 2 in `forecast.test.tsx`.

- [ ] **Step 5: Build, lint, commit**

```bash
cd frontend && npm run build && npm run lint
```

```bash
git add frontend/src/goals.ts frontend/src/goals.test.tsx frontend/src/forecast.ts frontend/src/forecast.test.tsx
git commit -m "feat: goal and forecast hooks for the web client"
```

---

### Task 12: The Goals page

**Files:**
- Create: `frontend/src/GoalCards.tsx`
- Create: `frontend/src/GoalCards.test.tsx`
- Create: `frontend/src/pages/GoalsPage.tsx`

**Interfaces:**
- Consumes: `useGoals`, `useCreateGoal`, `useUpdateGoal`, `useDeleteGoal`, `goalPercent`, `type Goal` (Task 11); `useAccounts` from `./data`; `usd`, `shortDate` from `./money`; `Card`, `Empty`, `PageHead` from `./ui/Shell`.
- Produces: `GoalCards()`, `GoalsPage()`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/GoalCards.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GoalCards } from "./GoalCards";
import type { Goal } from "./goals";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const goal = (over: Partial<Goal> = {}): Goal => ({
  id: "g1",
  name: "Emergency Fund",
  kind: "savings",
  target_amount: "1000.0000",
  target_date: null,
  monthly_funding: null,
  status: "active",
  account_ids: [],
  progress: "400.0000",
  projected_date: "2026-09-01",
  ...over,
});

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <GoalCards />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("GoalCards", () => {
  it("shows a goal's name, progress, and target", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/goals") return [goal()];
      if (path === "/accounts") return [];
      return [];
    });
    show();
    expect(await screen.findByText("Emergency Fund")).toBeInTheDocument();
    expect(screen.getByText(/\$400\.00 of \$1,000\.00/)).toBeInTheDocument();
  });

  it("shows an empty state with no goals", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => (path === "/goals" ? [] : []));
    show();
    expect(await screen.findByText("No goals yet — add one above.")).toBeInTheDocument();
  });

  it("submitting the new-goal form posts a create request", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/goals" && opts?.method === "POST") return goal();
      if (path === "/goals") return [];
      if (path === "/accounts") return [];
      return [];
    });
    show();
    fireEvent.change(await screen.findByLabelText("Goal name"), { target: { value: "Vacation" } });
    fireEvent.change(screen.getByLabelText("Target amount"), { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add goal" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/goals",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("clicking delete removes the goal", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/goals" && (!opts || opts.method === undefined)) return [goal()];
      if (path === "/accounts") return [];
      if (path === `/goals/${goal().id}` && opts?.method === "DELETE") return { status: "ok" };
      return [];
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: `Delete ${goal().name}` }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(`/goals/${goal().id}`, expect.objectContaining({ method: "DELETE" })),
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- GoalCards`
Expected: FAIL — cannot resolve `./GoalCards`.

- [ ] **Step 3: Write the component**

Create `frontend/src/GoalCards.tsx`:

```tsx
import { useState } from "react";
import { useAccounts } from "./data";
import { goalPercent, useCreateGoal, useDeleteGoal, useGoals, useUpdateGoal } from "./goals";
import type { Goal } from "./goals";
import { shortDate, usd } from "./money";
import { Card, Empty } from "./ui/Shell";

function GoalRing({ percent }: { percent: number }) {
  const r = 26;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - percent / 100);
  return (
    <svg width={64} height={64} viewBox="0 0 64 64" role="img" aria-label={`${Math.round(percent)}% funded`}>
      <circle cx={32} cy={32} r={r} fill="none" stroke="var(--color-line)" strokeWidth={6} />
      <circle
        cx={32}
        cy={32}
        r={r}
        fill="none"
        stroke="#c6f24e"
        strokeWidth={6}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 32 32)"
      />
      <text x={32} y={36} textAnchor="middle" className="tnum" fontSize={13} fill="currentColor">
        {Math.round(percent)}%
      </text>
    </svg>
  );
}

function GoalRow({ goal }: { goal: Goal }) {
  const percent = goalPercent(goal);
  const update = useUpdateGoal(goal.id);
  const del = useDeleteGoal();
  return (
    <li className="flex items-center gap-4 border-b border-line py-4 last:border-0">
      <GoalRing percent={percent} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{goal.name}</p>
        <p className="tnum mt-0.5 text-xs text-muted">
          {usd(goal.progress)} of {usd(goal.target_amount)}
          {goal.projected_date && <> · projected {shortDate(goal.projected_date)}</>}
        </p>
      </div>
      <button
        className="text-xs text-muted transition-colors hover:text-bone"
        aria-label={`Archive ${goal.name}`}
        onClick={() => update.mutate({ status: "archived" })}
      >
        Archive
      </button>
      <button
        className="text-xs text-clay"
        aria-label={`Delete ${goal.name}`}
        onClick={() => del.mutate(goal.id)}
      >
        Delete
      </button>
    </li>
  );
}

function NewGoalForm() {
  const { data: accounts = [] } = useAccounts();
  const create = useCreateGoal();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"savings" | "debt_payoff">("savings");
  const [targetAmount, setTargetAmount] = useState("");
  const [accountIds, setAccountIds] = useState<string[]>([]);

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          { name, kind, target_amount: targetAmount, account_ids: accountIds },
          {
            onSuccess: () => {
              setName("");
              setTargetAmount("");
              setAccountIds([]);
            },
          },
        );
      }}
    >
      <label className="flex flex-col gap-1 text-xs">
        Goal name
        <input aria-label="Goal name" value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Kind
        <select aria-label="Goal kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="savings">Savings</option>
          <option value="debt_payoff">Debt payoff</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Target amount
        <input
          aria-label="Target amount"
          value={targetAmount}
          onChange={(e) => setTargetAmount(e.target.value)}
          inputMode="decimal"
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Linked accounts
        <select
          aria-label="Linked accounts"
          multiple
          value={accountIds}
          onChange={(e) => setAccountIds(Array.from(e.target.selectedOptions, (o) => o.value))}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <button className="btn" disabled={create.isPending}>
        Add goal
      </button>
    </form>
  );
}

export function GoalCards() {
  const { data: goalList = [], isLoading } = useGoals();

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Your goals</h2>
      <NewGoalForm />
      <div className="mt-6">
        {isLoading ? null : goalList.length === 0 ? (
          <Empty>No goals yet — add one above.</Empty>
        ) : (
          <ul>
            {goalList.map((g) => (
              <GoalRow key={g.id} goal={g} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
```

Create `frontend/src/pages/GoalsPage.tsx`:

```tsx
import { GoalCards } from "../GoalCards";
import { PageHead } from "../ui/Shell";

export function GoalsPage() {
  return (
    <>
      <PageHead title="Goals" sub="Savings targets and debt payoff, tracked against real balances" />
      <GoalCards />
    </>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- GoalCards`
Expected: PASS — 4 tests.

- [ ] **Step 5: Build, lint, commit**

```bash
cd frontend && npm run build && npm run lint
```

```bash
git add frontend/src/GoalCards.tsx frontend/src/GoalCards.test.tsx frontend/src/pages/GoalsPage.tsx
git commit -m "feat: the Goals page, with progress rings and a projected date"
```

---

### Task 13: The Overview forecast chart and "can I afford"

**Files:**
- Create: `frontend/src/ForecastChart.tsx`
- Create: `frontend/src/ForecastChart.test.tsx`
- Modify: `frontend/src/pages/OverviewPage.tsx`

**Interfaces:**
- Consumes: `AreaChart` from `./charts` (already shipped); `useForecast`, `useAfford`, `firstNegativeDay` (Task 11); `usd` from `./money`; `Card`, `Empty` from `./ui/Shell`.
- Produces: `ForecastChart()`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/ForecastChart.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForecastChart } from "./ForecastChart";
import type { ForecastDay } from "./forecast";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const days = (): ForecastDay[] => [
  { on: "2026-07-01", projected_balance: "1000.00", contributions: [] },
  { on: "2026-07-02", projected_balance: "900.00", contributions: [] },
  { on: "2026-07-03", projected_balance: "-50.00", contributions: ["Rent -950.00"] },
];

function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ForecastChart />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("ForecastChart", () => {
  it("shows a negative-balance marker when the forecast dips below zero", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => (path.startsWith("/forecast?") ? days() : days()));
    show();
    expect(await screen.findByText(/Projected to go negative on 2026-07-03/)).toBeInTheDocument();
  });

  it("shows no marker when the forecast never goes negative", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { on: "2026-07-01", projected_balance: "1000.00", contributions: [] },
      { on: "2026-07-02", projected_balance: "900.00", contributions: [] },
    ]);
    show();
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(screen.queryByText(/Projected to go negative/)).not.toBeInTheDocument();
  });

  it("submitting the can-I-afford form posts to /forecast/afford and shows the verdict", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
      if (path === "/forecast/afford" && opts?.method === "POST") {
        return {
          baseline: days(), with_amount: days(), stays_non_negative: true,
          minimum_balance: "50.00", goal_impact: [],
        };
      }
      return days();
    });
    show();
    fireEvent.change(await screen.findByLabelText("Amount"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-07-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/stays at \$50\.00/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- ForecastChart`
Expected: FAIL — cannot resolve `./ForecastChart`.

- [ ] **Step 3: Write the component**

Create `frontend/src/ForecastChart.tsx`:

```tsx
import { useState } from "react";
import { AreaChart } from "./charts";
import { firstNegativeDay, useAfford, useForecast } from "./forecast";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

export function ForecastChart() {
  const { data: days = [] } = useForecast(6);
  const [amount, setAmount] = useState("");
  const [onDate, setOnDate] = useState("");
  const afford = useAfford();

  const negative = firstNegativeDay(days);

  return (
    <Card className="mt-4" delay={200}>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-sm font-medium">Cash flow forecast</h2>
        <span className="label">Next 6 months</span>
      </div>

      {days.length < 2 ? (
        <Empty>Not enough data yet to project a forecast.</Empty>
      ) : (
        <>
          <AreaChart
            valueLabel="Projected balance"
            points={days.map((d) => ({ label: d.on, value: Number(d.projected_balance) }))}
          />
          {negative && (
            <p className="mt-2 text-[11px] text-clay">
              Projected to go negative on {negative.on}
            </p>
          )}
        </>
      )}

      <form
        className="mt-5 flex flex-wrap items-end gap-3 border-t border-line pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          afford.mutate({ amount, on_date: onDate, months: 6 });
        }}
      >
        <label className="flex flex-col gap-1 text-xs">
          Can I afford…
          <input
            aria-label="Amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="500"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Date
          <input aria-label="Date" type="date" value={onDate} onChange={(e) => setOnDate(e.target.value)} />
        </label>
        <button className="btn" disabled={afford.isPending}>
          Check
        </button>
      </form>

      {afford.data && (
        <p className="mt-3 text-sm">
          {afford.data.stays_non_negative
            ? `Yes — the lowest projected balance stays at ${usd(afford.data.minimum_balance)}.`
            : `This would take the balance to ${usd(afford.data.minimum_balance)} — below zero.`}
        </p>
      )}
    </Card>
  );
}
```

In `frontend/src/pages/OverviewPage.tsx`, add the import:

```tsx
import { ForecastChart } from "../ForecastChart";
```

and mount it right after the existing "Net worth over time" `<Card>` (the one wrapping `<NetWorthChart points={history} />`) and before the `<div className="grid gap-4 lg:grid-cols-[3fr_2fr]">` cash-flow/merchants row:

```tsx
      <ForecastChart />

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- ForecastChart`
Expected: PASS — 3 tests.

- [ ] **Step 5: Build, lint, commit**

```bash
cd frontend && npm run build && npm run lint
```

```bash
git add frontend/src/ForecastChart.tsx frontend/src/ForecastChart.test.tsx frontend/src/pages/OverviewPage.tsx
git commit -m "feat: a forecast chart on Overview, with a negative-balance marker and can-I-afford"
```

---

### Task 14: Route, navigation, README/CHANGELOG, and end-to-end flow

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/ui/Shell.tsx`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Create: `frontend/e2e/goals.spec.ts`

**Interfaces:**
- Consumes: `GoalsPage` (Task 12).
- Produces: `/goals` route; a "Goals" navigation entry.

- [ ] **Step 1: Add the route**

In `frontend/src/App.tsx`, add the import:

```tsx
import { GoalsPage } from "./pages/GoalsPage";
```

and a new `<Route>`, alongside the existing `/recurring` one:

```tsx
          <Route
            path="/goals"
            element={
              <Protected>
                <GoalsPage />
              </Protected>
            }
          />
```

- [ ] **Step 2: Navigation — check reality first, then follow the matching branch**

Run: `grep -n "MORE" frontend/src/ui/Shell.tsx` (or open the file and look).

**Branch A — a `MORE` array exists (P2 merged and built it per its own plan).** Add exactly one entry, after whatever P2 put there, and touch nothing else in the file:

```tsx
  { to: "/goals", label: "Goals", short: "Goals", glyph: "◎" },
```

Do not rename `NAV`, do not touch `MoreMenu.tsx`, do not add a fifth entry to the phone tab bar. This is the entire task in this branch.

**Branch B — no `MORE` array exists (the state verified at the top of this plan, current as of 2026-08-01).** P2's own MoreMenu plan hasn't landed, so there is nothing to add one entry to. The five-tab phone ceiling documented in PLAN-CONSTRAINTS.md still applies, and adding a sixth item to `NAV` violates it — so this branch does **not** silently ship a 6-tab bar. Instead:

1. Add "Goals" to the desktop-only sidebar `NAV` array in `frontend/src/ui/Shell.tsx:5-13` is **not** done, because `NAV` also drives the mobile tab bar (the same array renders both, lines 30-54 and 89-110) — there is no separate desktop-only list to extend without either P2's MoreMenu split or a second array this plan would have to invent (which is P2's job, not P3's).
2. Instead, link to Goals from the Overview page only, next to the forecast chart Task 13 already added — add a small link in `frontend/src/pages/OverviewPage.tsx`, right after the `<ForecastChart />` line:

```tsx
      <p className="mt-2 text-right text-[11px]">
        <Link to="/goals" className="label transition-colors hover:text-bone">
          View goals →
        </Link>
      </p>
```

(`Link` is already imported in `OverviewPage.tsx` from `react-router-dom`.)

3. Leave a comment at the top of `frontend/src/ui/Shell.tsx` recording why:

```tsx
// ponytail: Goals has no NAV/MORE entry yet — P2's MoreMenu split (PLAN-CONSTRAINTS.md,
// "Navigation") hasn't landed as of P3. The route exists (/goals) and Overview links to
// it directly. When P2 ships MoreMenu.tsx and a MORE array, add one entry here for
// Goals and delete the Overview link — do not leave both.
```

Whichever branch applies, this step's own commit message must say which branch was taken, so a later reader isn't left guessing.

- [ ] **Step 3: README and CHANGELOG**

In `README.md`, under "## What's here", add a bullet after the Categories one:

```markdown
- **Goals** — savings and debt-payoff targets, linked to the real accounts that fund
  them; progress is always today's actual balance, never a separate ledger that can
  drift from it. A cash-flow forecast on Overview projects forward from today's
  balances, your recurring bills, and this month's budget — with a "can I afford…"
  check that shows what a hypothetical purchase does to the projection and to every
  active goal's date.
```

In `CHANGELOG.md`, add a new section above the P1 entry:

```markdown
## P3 (goals and cash-flow forecast) — on its own branch, not yet merged

### Added
- `goals` and `goal_accounts` tables: a savings or debt-payoff target and the
  accounts whose balances count toward it. No contributions ledger — progress is
  always the linked accounts' current balance, sign-flipped for debt payoff.
- `services/forecast.py::project` — a daily balance walk from today's cash accounts,
  applying every active recurring series' cadence and the current month's uncovered
  budget spread evenly, plus any hypothetical passed in.
- `can_i_afford`: runs the forecast twice, with and without a hypothetical outflow,
  and reports whether the balance would go negative and what it does to every active
  goal's projected date.
- `GET/POST /goals`, `PATCH/DELETE /goals/{id}`, `GET /forecast?months=`,
  `POST /forecast/afford`.
- Frontend: a Goals page with progress rings and a projected date per goal; a
  forecast chart on Overview with a negative-balance marker and a "can I
  afford…" input.
```

- [ ] **Step 4: End-to-end flow**

Create `frontend/e2e/goals.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
test("create a goal, link an account, and see it on the Goals page", async ({ page }) => {
  const stamp = Date.now();
  const account = `Goal Savings ${stamp}`;
  const goalName = `Vacation ${stamp}`;

  await page.goto("/accounts");
  await page.getByPlaceholder("Main Checking").fill(account);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(account)).toBeVisible();

  await page.goto("/goals");
  await page.getByLabel("Goal name").fill(goalName);
  await page.getByLabel("Target amount").fill("2000");
  await page.getByLabel("Linked accounts").selectOption({ label: account });
  await page.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByText(goalName)).toBeVisible();

  // Clean up after ourselves — this runs against the real local database.
  await page.getByRole("button", { name: `Delete ${goalName}` }).click();
  await expect(page.getByText(goalName)).toHaveCount(0);
  await page.goto("/accounts");
  await page.getByRole("button", { name: `Remove ${account}` }).click();
  await page.getByRole("button", { name: "Delete account and its transactions" }).click();
  await expect(page.getByText(`${account} (savings)`)).toHaveCount(0);
});
```

- [ ] **Step 5: Run the full frontend suite, build, lint**

```bash
cd frontend && npm test && npm run build && npm run lint
```

Expected: PASS.

- [ ] **Step 6: Run the full backend suite one more time**

```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

Expected: PASS — this is the final gate before commit, covering everything Tasks 1–14 touched together.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/ui/Shell.tsx frontend/src/pages/OverviewPage.tsx \
        README.md CHANGELOG.md frontend/e2e/goals.spec.ts
git commit -m "feat: wire up Goals — route, navigation, docs, and an e2e flow"
```

---

## Self-Review

### 1. Spec coverage

Checked against `docs/superpowers/specs/2026-07-30-origin-parity-design.md` lines 262–334 (P3) plus §6–8:

| Spec item | Covered by |
|---|---|
| `goals` table (id, household_id, name, kind, target_amount, target_date, monthly_funding, status, created_at) | Task 1 |
| `goal_accounts` join table, composite PK | Task 1 |
| Progress = summed linked balance, sign-flipped for debt_payoff, no contributions ledger | Tasks 2–3 |
| `project(db, hid, months, hypotheticals=[])`, 5 numbered steps | Tasks 4–6 (steps 1,2,4,5 in Task 4; step 3 in Task 5) |
| `can_i_afford(db, hid, amount, on_date, months)` | Task 6 |
| `goal_projection(db, hid, goal_id)` | Task 7 |
| `GET/POST /goals`, `PATCH/DELETE /goals/{id}` | Task 9 |
| `GET /forecast?months=6`, `POST /forecast/afford` | Task 10 |
| UI: Goals page, progress rings, projected dates | Task 12 |
| UI: forecast chart on Overview with negative-balance marker | Task 13 |
| UI: "Can I afford…" input | Task 13 |
| Test: cadence walking across month ends and leap day | Task 4 (`test_monthly_cadence_clamps_at_month_end...`, `test_monthly_cadence_lands_on_a_real_leap_day`) |
| Test: biweekly drift over a year | Task 4 (`test_biweekly_cadence_drifts_across_a_calendar_year`) |
| Test: a series whose next_expected_on is in the past | Task 4 (`test_a_series_whose_next_expected_on_is_in_the_past_is_fast_forwarded`) |
| Test: forecast with zero recurring series | Task 4 (`test_forecast_with_zero_recurring_series_is_a_flat_line...`) |
| Test: can_i_afford on an amount that empties the account | Task 6 (`test_can_i_afford_an_amount_that_empties_the_account`) |
| Test: debt-payoff progress direction | Task 3 (`test_progress_for_debt_payoff_is_the_amount_paid_down_from_target`) |
| Test: goal with no linked accounts | Task 3 (`test_progress_for_a_goal_with_no_linked_accounts_is_zero_for_either_kind`) |
| Cut: avalanche/snowball, Monte Carlo, retirement projection | None of Tasks 1–14 build any of these; stated explicitly in Global Constraints |
| Tenancy test appended to `test_tenancy.py` | Task 10 |
| One Alembic revision for this phase | Task 1 (`f4a29c7d1e63`) |
| §6 index on `transactions (household_id, category_id, posted_at)` | Already P1's responsibility, not re-specified here |
| §6 "nothing new in the dependency tree" | Global Constraints — flags Recharts isn't actually installed and builds on the real `charts.tsx` instead |
| Navigation: P3 adds one entry to `MORE`, doesn't rebuild the menu | Task 14, with the two-branch instruction for whichever state (P2 merged or not) is real at execution time |

No gaps found.

### 2. Placeholder scan

Searched for "TBD", "TODO", "implement later", "add appropriate", "handle edge cases", "similar to Task N" (without inline code), and bare prose describing code without showing it. None found. The two spots that look like a deferred computation — Task 4's `daily_discretionary = Decimal("0")` and Task 6/7's shared `_goal_date_from_series` growing across tasks — both carry the exact same shape P2's plan already used for `carry_in = Decimal("0")` in its Task 3 (a real, working value for that task's scope, explicitly documented as replaced by a later task, not a "fill this in" marker) and are not placeholders under the skill's own definition.

### 3. Type consistency

Checked every symbol that crosses a task boundary:

- `Goal`, `GoalAccount`, `GoalKind`, `GoalStatus` (Task 1) → used identically in Tasks 2, 3, 6, 7, 9, 10.
- `goals.UnknownAccount`, `goals.UnknownGoal` (Task 2) → caught by name in Task 9's router and Task 10's tenancy test; no renamed variant appears anywhere.
- `goals.create(db, household_id, *, name, kind, target_amount, target_date=None, monthly_funding=None, account_ids=None)` (Task 2) → called with these exact keyword names in Tasks 3, 6, 7, and `test_goals_api.py` via the `GoalCreate` schema's matching field names.
- `goals.update(db, household_id, goal_id, data: GoalUpdate)` (Task 2) → called with a `GoalUpdate` instance, never a dict or a different dataclass, in Tasks 2, 6, and 9.
- `goals.progress_for(db, household_id, goal) -> Decimal` (Task 2) → same signature used in Tasks 3, 6 (`_goal_date_from_series`), 7 (`goals_overview`).
- `forecast.Hypothetical(amount, on_date, label="Hypothetical")` (Task 4) → same three fields used identically in Task 6's `can_i_afford`.
- `forecast.ForecastDay(on, projected_balance, contributions)` (Task 4) → same three fields read by Task 6's `can_i_afford`, Task 7's `_goal_date_from_series`, Task 8's `ForecastDayOut`, Task 10's router, Task 13's `ForecastChart`.
- `forecast.project(db, household_id, months, hypotheticals=None, *, today=None) -> list[ForecastDay]` (Task 4, extended in Task 5) → this exact signature is what Tasks 6, 7, 9, and 10 call; no task introduces a second, differently-shaped `project`.
- `forecast.UnknownGoal` (Task 7, distinct from `goals.UnknownGoal` from Task 2 — deliberately: `goal_projection`/`can_i_afford` raise the forecast module's own exception since `goals.get`/`goals.list_for` never raise on a missing id, they return `None`/`[]`) → Task 7's test catches `forecast.UnknownGoal`, not `goals.UnknownGoal`; Task 9's router never needs to catch it since it doesn't call `goal_projection` directly (it calls `goals_overview`, which never raises).
- `forecast.GoalOverview(goal_id, progress, projected_date)` (Task 7) → consumed with these exact field names in Task 9's `_out()`.
- Frontend `Goal` type (Task 11) field names (`account_ids`, `progress`, `projected_date`, all others) → match `GoalOut`'s field names exactly (Task 8); `ForecastDay`/`AffordResult` (Task 11) match `ForecastDayOut`/`AffordOut` (Task 8) field-for-field, money fields as `string` throughout.
- `goalPercent(goal: Goal): number` (Task 11) → same name and signature used in Task 12's `GoalCards.tsx`.
- `firstNegativeDay(days: ForecastDay[]): ForecastDay | null` (Task 11) → same name and signature used in Task 13's `ForecastChart.tsx`.

No mismatches found.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-01-p3-goals-forecast.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
