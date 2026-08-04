# P5 Reports, Tax, and Document Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A household can see where its money went (by category, merchant, or month), see income against expense over a year, get a year-in-review summary, pull FIFO realized gains and a dividend/interest total for tax season, export a Schedule-D-shaped CSV that says on its face what it doesn't do (wash sales), upload estate documents that are encrypted before they ever touch disk, see a computed checklist of estate-planning gaps, and download every table it owns as one zip of CSVs. Nothing here drafts a document, gives tax advice, or detects a wash sale — this phase reports what already happened; it never decides what should happen next.

**Architecture:** Reports add no tables — `services/reports.py` is three read functions over `Transaction` rows the app already has, relying on the `(household_id, category_id, posted_at)` index P1's migration already created. Tax realized gains is a from-scratch FIFO lot replay over `models/trade.py` in `services/tax.py`, deliberately separate from `services/portfolio.py`'s average-cost engine — portfolio.py answers "what's this worth today" for the holdings page, FIFO answers "what did I actually realize this year" for a tax form, and they are different methods for different questions, not two implementations of one. The vault is one new table, `documents`, whose files are encrypted with the AES-GCM envelope `app/core/encryption.py` already implements for provider credentials (`app/providers/base.py`) — the whole file is read into memory, sealed once with `encrypt()`, and written to disk as one opaque blob; plaintext exists only for the duration of an upload or a download. `accounts.beneficiary` is one nullable column, not a model. The estate checklist and the `/export/all.zip` endpoint are both computed reads: the checklist has no storage of its own, and the export enumerates `Base.metadata` at runtime rather than a hand-maintained table list, so a new household-scoped model is a fact the export test can catch rather than a step someone has to remember.

**Tech Stack:** FastAPI, SQLAlchemy 2 (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + testcontainers Postgres, React 19, TanStack Query, react-hook-form, Vitest, Playwright. No new dependencies — no PDF library, no OCR library, no zip library beyond the standard library's `zipfile`/`csv`.

---

## STOP — read this before Task 12

This plan implements **P5**, which the spec (`docs/superpowers/specs/2026-07-30-origin-parity-design.md`, §5 "P5 — Reports, tax, and the document vault") states depends on **P1 only** — "reports are category-shaped," and every other P5 feature (tax, vault, estate, export) reads `models/trade.py`, `models/account.py`, and `Base.metadata` directly, none of it through P2's budgets, P3's goals/forecast, or P4's advisor tools. Tasks 1–11 touch nothing any of those three phases own and can be built and tested regardless of their status.

**Task 12 is the one exception**, because PLAN-CONSTRAINTS.md's Navigation section says P5 adds one entry to a `MORE` array in `frontend/src/ui/Shell.tsx` that **P2's own plan is supposed to have already built**. As of the date this plan was written (2026-08-02), that hasn't happened, verified directly rather than assumed:

- `backend/app/models/budget.py`, `backend/app/models/goal.py`, `backend/app/services/forecast.py`, `backend/app/services/advisor_tools.py` do not exist.
- `cd backend && .venv/Scripts/python -m alembic heads` returns `e1f3a2c4b508` — P1's own migration — with nothing from P2, P3, or P4 on top of it.
- `git branch -a` shows only `main`, `oracle-hosting`, and `p1-categorization`. There is no `p2-budgets`, `p3-goals-forecast`, or `p4-ai-advisor-v2` branch anywhere, local or remote.
- `frontend/src/ui/Shell.tsx` still has its original five-entry `NAV` array (Overview, Accounts, Investments, Transactions, Recurring) — no `MoreMenu.tsx`, no `MORE` array. `frontend/src/App.tsx` has no `/budgets`, `/goals`, or advisor-specific routes beyond the existing Overview assistant card.

**Before starting Task 12, re-run the verification above** (`ls backend/app/models/budget.py`, `.venv/Scripts/python -m alembic heads`, check for `MORE` in `Shell.tsx`). Task 12 gives an explicit two-branch instruction for whichever state is real at execution time — see that task; it is not a guess written on top of code that isn't there. If `MoreMenu.tsx` exists, P5 adds exactly one entry to its `MORE` array and touches nothing else in that file, per PLAN-CONSTRAINTS.md. If it doesn't, Task 12 documents the same fallback P3's own plan used for the identical problem (a direct link from Overview, with a `ponytail:` comment naming what to undo once P2 ships the menu).

---

## Global Constraints

Carried forward from `docs/superpowers/plans/PLAN-CONSTRAINTS.md`, restated for this plan:

- **Money** is `Decimal` in Python and `NUMERIC(19,4)` in Postgres, and a **string** once it crosses into TypeScript. Never `float`, never `number`, not even for display arithmetic. Every dollar figure this plan produces — spending totals, realized gains, cost bases, dividend/interest sums, savings rate — follows this. `size_bytes` on `documents` is a plain integer (a byte count, not money) and stays `int`/`Integer`, not `Decimal`/`Numeric`.
- **Tenancy.** Every function in `services/reports.py`, `services/tax.py`, `services/documents.py`, `services/estate.py`, and `services/export.py` takes `household_id` and filters on it. A document id, once documents exist, is checked the same way `categories.get`/`accounts.get` already are — a foreign household's id resolves to `None`/404, never a 500 and never someone else's bytes. Task 7 gives this its own tenancy test, and Task 9's export test asserts every CSV in the zip contains only rows for the requesting household.
- **No new dependencies.** No PDF library (PDF report rendering is cut), no OCR library (cut), no zip library beyond the standard library's `zipfile` and `csv` — both already available with no `pyproject.toml` change. No charting library beyond `frontend/src/charts.tsx`'s hand-rolled `AreaChart`/`BarChart`/`AllocationBar` — `recharts` is not installed (see P3's own plan, which verified this directly) and this plan does not add it.
- **The gates**, from `backend/`: `.venv/Scripts/python.exe -m pytest -q`, `.venv/Scripts/python.exe -m ruff check app`, `.venv/Scripts/python.exe -m mypy app`. From `frontend/`: `npm test`, `npm run build`, `npm run lint`.
- **`npm run build`, never `npm run typecheck`.** `typecheck` is `tsc --noEmit`; `build` is `tsc -b`, and they check different things — P1 shipped behind a green `typecheck` while `build` had been broken the whole time. Every gate step in this plan says `build`.
- **Pre-existing baseline, not this plan's to fix:** `ruff check app` reports 3 and `mypy app` reports 24 pre-existing errors in `portfolio.py`, `trade_import.py`, `scheduler.py`, `investments.py`, `prices.py`, `recurring.py`. The gate is **no new errors in files this plan touches.** `frontend/e2e/mobile.spec.ts` is pre-existing-broken (a non-exact heading matcher) and not this plan's concern.
- **Backend tests need Docker running** — `conftest.py` starts a real `postgres:17` container.
- **Test fixtures.** `backend/tests/conftest.py` provides only `pg_engine` and `db`. There is no shared `household`, `account`, or `client` fixture. Every test file this plan creates defines its own, following the exact shape already in `backend/tests/test_categories_api.py`: a `household` fixture, an `account` fixture depending on it, and a `client` fixture that overrides `get_db` and `require_household` on the real `app.main.app` instance.
- **Tests build the schema with `Base.metadata.create_all`, never with Alembic.** `backend/tests/test_migrations.py` is the one place that runs the real Alembic chain; nothing else in this plan needs to.
- **Vite module resolution.** `./reports` would resolve to `reports.ts` before any `reports.tsx` — so the reports hooks live in `reports.ts` and their components live in `ReportsCards.tsx`, never `reports.tsx`. Same split for `tax.ts`/no component file of its own (folded into `ReportsCards.tsx`) and `vault.ts`/`VaultPanel.tsx`.
- **React Testing Library.** `findByLabelText` on a `<select>` resolves as soon as the element exists, before an async options fetch has resolved — await the *option*, not the select, wherever a test needs one. `waitFor` returns on its first truthy check, so a regression assertion that starts out already true is a false negative.
- **House style.** Service modules are flat functions taking `(db, household_id, ...)`. Routers are thin and translate service exceptions into `HTTPException`. Comments explain *why*, never *what*. A deliberate shortcut with a known ceiling gets a `ponytail:` comment naming the ceiling and the upgrade path. One Alembic revision for this whole phase (Task 5). Commit subjects are lowercase and human, no task numbers.
- **The cut list is explicit and binding.** Per the spec's own §5 P5 section: PDF report rendering, document generation, OCR, wash-sale detection, cost-basis methods other than FIFO, and e-signature are **cut**. The word "advice" appears nowhere in any tax-facing UI string this plan writes. None of the thirteen tasks below build any of the cut items, and if a review of this plan finds one sneaking in under another name, that's a bug in the plan, not a feature to keep.

**Deviations from the spec's literal wording, recorded here rather than silently, mirroring how P2 and P3 recorded their own:**

1. **`documents` has no separate `nonce`/`wrapped_key` columns.** The spec's schema lists them "same envelope scheme as provider credentials," and the research step behind this plan went and read that scheme (`app/core/encryption.py`, used by `app/providers/base.py`). It exposes exactly two functions, `encrypt(plaintext: bytes, aad: bytes = b"") -> bytes` and `decrypt(blob: bytes, aad: bytes = b"") -> bytes`, and the blob `encrypt()` returns already contains a wrapped DEK and its own AES-GCM nonce internally — `ProviderConnection` itself stores this as one `encrypted_credentials: LargeBinary` column, not three. Giving `documents` a `nonce`/`wrapped_key` pair the real encryption module never produces would be dead columns or a second, unused low-level API invented just to fill them. `documents.ciphertext_path` names a file on disk holding exactly the bytes `encrypt()` returns; nothing about the envelope's shape needs a second home in the row.
2. **No `documents.updated_at`.** Every model in this codebase (`Category`, `Transaction`, `Account`, `Household`, `RecurringSeries`, `Trade`) uses `TimestampMixin`, which defines only `created_at` (`backend/app/models/base.py:17-18`) — no model anywhere tracks `updated_at`, and P3 already made the identical call for `Goal`. `Document` is not the first exception.
3. **`GET /tax/income-summary` reads dividends *and* interest from categorized transactions only** — never from `models/trade.py`'s own `dividend` `TradeType`. The spec's wording ("dividends + interest from categorized transactions") reads as both coming from the same source, and a brokerage dividend that lands as a bank-fed transaction row would double-count if this endpoint also walked the trade log. `services/tax.py::realized_gains` is the only place this phase reads the trade log directly; income summary reuses P1's `Income/Dividends` and `Income/Interest` system-category leaves instead.
4. **Realized gains are computed across every account, including tax-advantaged ones.** `models/account.py`'s `AccountType` enum has no way to mark an account as a taxable brokerage versus an IRA or 401(k) — only a generic `investment`. A real Schedule D never lists trades inside a retirement account. This export is a reporting tool over the data this schema actually has, not a filing tool, and its CSV carries a disclaimer about what it doesn't adjust for (wash sales) but this account-type gap is a second, separate limitation worth recording here rather than a claim of exactness the schema can't back up.
5. **The estate checklist's "retirement and insurance accounts" maps to `AccountType.investment`, and its "property accounts" maps to `AccountType.asset`.** The schema has no dedicated `retirement`, `insurance`, or `property` account type (`models/account.py` has nine types total: checking, savings, credit_card, loan, investment, crypto, cash, asset, liability). `investment` is the closest fit for something that names a beneficiary; `asset` is the closest fit for something a deed attaches to. Both are explicit, named choices in `services/estate.py`'s own comments, not a silent guess.
6. **The checklist's deed/title check compares *counts*, not per-account links.** `documents` has no `account_id` foreign key — the spec's own schema doesn't add one — so there is no way to confirm "this specific deed is for this specific property." The checklist instead asks "do you have at least as many deed/title documents on file as property accounts," which reports the gap the spec asks about without inventing a schema relationship the spec never requested.
7. **"New subscriptions started" and "subscriptions cancelled" in year-in-review use `first_charged_on`/`last_charged_on`, not a cancellation timestamp.** `models/recurring.py`'s `RecurringSeries` has no `cancelled_at` column — only a `status` enum and the two charge-date columns detection already maintains. "Cancelled during year Y" is approximated as "status is `cancelled` or `ended`, and the last charge detection ever saw was within year Y" — the best available signal, not an exact record of when the user clicked cancel.
8. **`GET /export/all.zip` excludes the `users` and `provider_connections` tables from its otherwise-automatic "every household table" rule.** Both have a `household_id` column and would otherwise qualify, but `users.password_hash` and `provider_connections.encrypted_credentials` are credential material, not financial data — the design spec's own "even better: exportable" claim (§4) is about financial history leaving with no lock-in, not about handing a household its own password hash in a CSV. This exclusion list is hardcoded independently in both `services/export.py` and its test (Task 9) — deliberately not imported from one into the other, so a new household-scoped model added later must be consciously routed to a CSV or added to the exclusion with a stated reason, rather than silently inheriting whichever list happens to already exist.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `backend/app/services/reports.py` | `spending`, `income_vs_expense`, `year_in_review` |
| `backend/app/schemas/report.py` | Pydantic out-schemas for the three reports endpoints |
| `backend/app/api/reports.py` | `/reports/spending`, `/reports/income-vs-expense`, `/reports/year-in-review` |
| `backend/app/services/tax.py` | FIFO `realized_gains`, `income_summary`, `export_csv` |
| `backend/app/schemas/tax.py` | Pydantic out-schemas for the three tax endpoints |
| `backend/app/api/tax.py` | `/tax/realized-gains`, `/tax/income-summary`, `/tax/export` |
| `backend/app/models/document.py` | `Document` model + `DocumentKind` enum |
| `backend/app/schemas/document.py` | `DocumentOut` |
| `backend/app/services/documents.py` | `save`, `get`, `list_for`, `read_plaintext`, `delete` — the envelope-encrypted vault |
| `backend/app/api/documents.py` | `/documents` list/upload/download/delete |
| `backend/app/services/estate.py` | Computed readiness checklist |
| `backend/app/schemas/estate.py` | `ChecklistOut` |
| `backend/app/api/estate.py` | `/estate/checklist` |
| `backend/app/services/export.py` | `build_zip` — every household table, one CSV each |
| `backend/app/api/export.py` | `/export/all.zip` |
| `backend/migrations/versions/b7e4a591c3d0_documents_and_beneficiary.py` | The one migration for this whole phase |
| `backend/tests/test_reports.py` | Service and router tests: `spending`, `income_vs_expense`, `year_in_review` |
| `backend/tests/test_tax.py` | FIFO service and router tests, including the CSV export's content |
| `backend/tests/test_documents.py` | Model, service, and router tests: round-trip, ciphertext-not-plaintext, tenancy |
| `backend/tests/test_estate.py` | Checklist gap-detection tests |
| `backend/tests/test_export.py` | Zip contains every household table, per the model registry |
| `frontend/src/reports.ts` | Hooks: `useSpending`, `useIncomeVsExpense`, `useYearInReview` |
| `frontend/src/tax.ts` | Hooks: `useRealizedGains`, `useIncomeSummary`, `taxExportUrl` |
| `frontend/src/vault.ts` | Hooks: `useDocuments`, `useChecklist`, `useUploadDocument`, `useDeleteDocument`, `documentDownloadUrl` |
| `frontend/src/ReportsCards.tsx` | `SpendingCard`, `CashFlowCard`, `YearInReviewCard`, `TaxCard` |
| `frontend/src/ReportsCards.test.tsx` | Component tests for the four cards |
| `frontend/src/VaultPanel.tsx` | `UploadForm`, `DocumentList`, `ChecklistCard` |
| `frontend/src/VaultPanel.test.tsx` | Component tests for the vault panel |
| `frontend/src/pages/ReportsPage.tsx` | Thin page: sub-tabs, mounts the cards above |
| `frontend/e2e/reports.spec.ts` | One end-to-end flow |

**Modify:**

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Register `Document`, `DocumentKind` |
| `backend/app/models/account.py` | Add `beneficiary: Mapped[str \| None]` |
| `backend/app/schemas/account.py` | Add `beneficiary` to `AccountCreate`/`AccountUpdate`/`AccountOut` |
| `backend/app/services/accounts.py` | Pass `beneficiary` through in `create` |
| `backend/app/core/config.py` | Add `documents_dir` setting |
| `backend/app/main.py` | Include the five new routers |
| `backend/tests/test_accounts.py` | Append a `beneficiary` round-trip test |
| `docker-compose.yml` | Named volume for the vault's encrypted files |
| `frontend/src/data.ts` | `Account` gains `beneficiary` |
| `frontend/src/App.tsx` | `/reports/*` route |
| `frontend/src/ui/Shell.tsx` | One `MORE` entry (or the documented fallback — see Task 12) |
| `frontend/src/pages/AccountDetailPage.tsx` | Beneficiary field in the edit form |
| `README.md`, `CHANGELOG.md` | P5 ships |

---

### Task 1: Reports — spending, grouped three ways

**Files:**
- Create: `backend/app/services/reports.py`
- Create: `backend/app/schemas/report.py`
- Create: `backend/app/api/reports.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_reports.py`

**Interfaces:**
- Consumes: `Transaction` (`app.models.transaction`), `Category` (`app.models.category`), `merchant_key` (`app.services.recurring`).
- Produces:
  - `class BadGroupBy(Exception)`
  - `VALID_GROUP_BY = {"category", "merchant", "month"}`
  - `SpendingBucket` dataclass: `key: str`, `key_id: uuid.UUID | None`, `total: Decimal`, `count: int`
  - `spending(db, household_id, start: date, end: date, group_by: str) -> list[SpendingBucket]`
  - Router `reports.router`, prefix `/reports`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_reports.py`:

```python
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.transaction import Transaction
from app.services import reports
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False

GROCERIES = system_category_id("Food & Drink/Groceries")
COFFEE = system_category_id("Food & Drink/Coffee")


@pytest.fixture
def household(db):
    row = Household(name="Reports Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.checking, name="Everyday", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    # For the router-level tests further down — same override pattern every API test
    # file in this plan uses.
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _txn(household, account, amount, merchant, on, category_id=None):
    return Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(on.year, on.month, on.day, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
        category_id=category_id,
    )


def test_spending_groups_by_category(db, household, account):
    ensure_system_categories(db)
    db.add_all(
        [
            _txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 7, 1), GROCERIES),
            _txn(household, account, "-8.00", "TRADER JOE", date(2026, 7, 5), GROCERIES),
            _txn(household, account, "-5.00", "BLUE BOTTLE", date(2026, 7, 2), COFFEE),
            _txn(household, account, "-3.00", "UNKNOWN SHOP", date(2026, 7, 10)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "category")

    assert [b.key for b in buckets] == ["Groceries", "Coffee", "Uncategorized"]
    assert buckets[0].total == Decimal("50.00")
    assert buckets[0].count == 2
    assert buckets[0].key_id == GROCERIES
    assert buckets[2].key_id is None


def test_spending_by_merchant_normalizes_store_numbers(db, household, account):
    db.add_all(
        [
            _txn(household, account, "-10.00", "WHOLE FOODS #1", date(2026, 7, 1)),
            _txn(household, account, "-10.00", "WHOLE FOODS #2", date(2026, 7, 2)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "merchant")

    assert len(buckets) == 1
    assert buckets[0].key == "whole foods"
    assert buckets[0].total == Decimal("20.00")
    assert buckets[0].count == 2


def test_spending_by_month_buckets_on_posted_month(db, household, account):
    db.add_all(
        [
            _txn(household, account, "-10.00", "A", date(2026, 6, 15)),
            _txn(household, account, "-20.00", "B", date(2026, 7, 1)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 6, 1), date(2026, 7, 31), "month")

    assert [b.key for b in buckets] == ["2026-07", "2026-06"]
    assert buckets[0].total == Decimal("20.00")


def test_spending_ignores_income_rows(db, household, account):
    db.add(_txn(household, account, "100.00", "PAYCHECK", date(2026, 7, 1)))
    db.commit()

    assert reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "category") == []


def test_spending_rejects_unknown_group_by(db, household, account):
    with pytest.raises(reports.BadGroupBy):
        reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "bogus")


def test_spending_endpoint_returns_grouped_buckets(client, db, household, account):
    db.add(_txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 7, 1)))
    db.commit()

    res = client.get("/reports/spending?start=2026-07-01&end=2026-07-31&group_by=merchant")
    assert res.status_code == 200
    body = res.json()
    assert body[0]["key"] == "whole foods"
    assert body[0]["total"] == "42.00"


def test_spending_endpoint_rejects_bad_group_by(client, db):
    res = client.get("/reports/spending?start=2026-07-01&end=2026-07-31&group_by=bogus")
    assert res.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_reports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.reports'`

- [ ] **Step 3: Write the service**

Create `backend/app/services/reports.py`:

```python
"""Aggregation reads over transactions the household already has. No new tables —
every figure here is a group-by over rows P1's categorization and the base
transaction log already produced. `spending` is the query cross-cutting §6 of the
design spec flags as the one query with real growth over a decade of history; it
relies on the `(household_id, category_id, posted_at)` index P1's migration already
added, and this file adds no second one.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.transaction import Transaction
from app.services.recurring import merchant_key

VALID_GROUP_BY = {"category", "merchant", "month"}


class BadGroupBy(Exception):
    """group_by outside {category, merchant, month}. The router's `Literal` type
    already rejects this at the HTTP boundary with a 422 before the service ever
    runs; this is the same belt-and-braces guard `categorization.compile_pattern`
    gives a direct caller of the service."""


@dataclass
class SpendingBucket:
    key: str
    key_id: uuid.UUID | None
    total: Decimal
    count: int


def _category_names(db: Session, household_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(Category.id, Category.name).where(
            (Category.household_id == household_id) | (Category.household_id.is_(None))
        )
    ).all()
    return {cid: name for cid, name in rows}


def spending(
    db: Session, household_id: uuid.UUID, start: date, end: date, group_by: str
) -> list[SpendingBucket]:
    """Spending — money out only — between `start` and `end` inclusive, grouped one of
    three ways. `total` is always positive: a bucket answers "how much left here", not
    a signed transaction sum."""
    if group_by not in VALID_GROUP_BY:
        raise BadGroupBy(group_by)

    since = datetime.combine(start, time.min, tzinfo=UTC)
    until = datetime.combine(end, time.max, tzinfo=UTC)
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.posted_at >= since,
                Transaction.posted_at <= until,
                Transaction.amount < 0,
            )
        )
    )
    if not txns:
        return []

    totals: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    ids: dict[str, uuid.UUID | None] = {}

    if group_by == "category":
        names = _category_names(db, household_id)
        for t in txns:
            k = str(t.category_id) if t.category_id else "uncategorized"
            totals[k] += -t.amount
            counts[k] += 1
            labels[k] = names.get(t.category_id, "Uncategorized") if t.category_id else "Uncategorized"
            ids[k] = t.category_id
    elif group_by == "merchant":
        for t in txns:
            k = merchant_key(t.merchant_normalized or t.merchant_raw)
            totals[k] += -t.amount
            counts[k] += 1
            labels[k] = k
            ids[k] = None
    else:  # month
        for t in txns:
            k = t.posted_at.strftime("%Y-%m")
            totals[k] += -t.amount
            counts[k] += 1
            labels[k] = k
            ids[k] = None

    buckets = [
        SpendingBucket(key=labels[k], key_id=ids[k], total=totals[k], count=counts[k]) for k in totals
    ]
    buckets.sort(key=lambda b: -b.total)
    return buckets
```

- [ ] **Step 4: Write the schema and router**

Create `backend/app/schemas/report.py`:

```python
import uuid
from decimal import Decimal

from pydantic import BaseModel


class SpendingBucketOut(BaseModel):
    key: str
    key_id: uuid.UUID | None
    total: Decimal
    count: int
```

Create `backend/app/api/reports.py`:

```python
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.report import SpendingBucketOut
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/spending", response_model=list[SpendingBucketOut])
def get_spending(
    start: date,
    end: date,
    group_by: Literal["category", "merchant", "month"] = "category",
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[SpendingBucketOut]:
    try:
        buckets = reports.spending(db, hid, start, end, group_by)
    except reports.BadGroupBy:
        raise HTTPException(status_code=422, detail="group_by must be category, merchant, or month")
    return [SpendingBucketOut(key=b.key, key_id=b.key_id, total=b.total, count=b.count) for b in buckets]
```

In `backend/app/main.py`, add `reports` to the `from app.api import (...)` tuple and `app.include_router(reports.router)` alongside the others.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_reports.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 6: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/reports.py backend/app/schemas/report.py backend/app/api/reports.py \
        backend/app/main.py backend/tests/test_reports.py
git commit -m "feat: spending, grouped by category, merchant, or month"
```

---

### Task 2: Reports — income vs. expense and year-in-review

**Files:**
- Modify: `backend/app/services/reports.py`
- Modify: `backend/app/schemas/report.py`
- Modify: `backend/app/api/reports.py`
- Test: `backend/tests/test_reports.py` (append)

**Interfaces:**
- Consumes: `spending` (Task 1); `net_worth_series` (`app.services.snapshots`); `RecurringSeries`, `SeriesStatus` (`app.models.recurring`).
- Produces:
  - `MonthFlow` dataclass: `month: str`, `income: Decimal`, `expense: Decimal`, `net: Decimal`
  - `income_vs_expense(db, household_id, months: int = 12) -> list[MonthFlow]`
  - `YearInReview` dataclass — see spec fields below
  - `year_in_review(db, household_id, year: int) -> YearInReview`
  - Two new routes on `reports.router`: `/income-vs-expense`, `/year-in-review`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_reports.py`:

```python
from datetime import UTC as _UTC  # noqa: F401  (already imported above; kept explicit for the diff)

from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.snapshot import BalanceSnapshot


def test_income_vs_expense_covers_every_month_even_empty_ones(db, household, account):
    today = datetime.now(UTC).date()
    current_key = today.replace(day=1).strftime("%Y-%m")
    db.add(_txn(household, account, "3000.00", "PAYCHECK", today.replace(day=1)))
    db.add(_txn(household, account, "-500.00", "RENT", today.replace(day=1)))
    db.commit()

    result = reports.income_vs_expense(db, household.id, months=12)

    assert len(result) == 12
    assert result[-1].month == current_key
    this_month = next(m for m in result if m.month == current_key)
    assert this_month.income == Decimal("3000.00")
    assert this_month.expense == Decimal("500.00")
    assert this_month.net == Decimal("2500.00")
    # A month with no transactions still appears, at zero — a gap in the chart is a
    # real answer ("nothing happened"), not a row that should vanish.
    assert any(m.income == Decimal(0) and m.expense == Decimal(0) for m in result)


def test_year_in_review_computes_expected_fields(db, household, account):
    ensure_system_categories(db)
    electronics = system_category_id("Shopping/Electronics")
    db.add_all(
        [
            _txn(household, account, "3000.00", "PAYCHECK", date(2026, 1, 15)),
            _txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 3, 1), GROCERIES),
            _txn(household, account, "-8.00", "BLUE BOTTLE", date(2026, 3, 2), COFFEE),
            _txn(household, account, "-500.00", "APPLE STORE", date(2026, 5, 1), electronics),
        ]
    )
    db.add(
        RecurringSeries(
            household_id=household.id,
            merchant_key="netflix",
            label="Netflix",
            cadence=Cadence.monthly,
            status=SeriesStatus.active,
            direction=-1,
            typical_amount=Decimal("15.00"),
            last_amount=Decimal("15.00"),
            min_amount=Decimal("15.00"),
            max_amount=Decimal("15.00"),
            charge_count=3,
            first_charged_on=date(2026, 2, 1),
            last_charged_on=date(2026, 4, 1),
            confidence=90,
        )
    )
    db.add(
        RecurringSeries(
            household_id=household.id,
            merchant_key="gym",
            label="Gym",
            cadence=Cadence.monthly,
            status=SeriesStatus.cancelled,
            direction=-1,
            typical_amount=Decimal("40.00"),
            last_amount=Decimal("40.00"),
            min_amount=Decimal("40.00"),
            max_amount=Decimal("40.00"),
            charge_count=3,
            first_charged_on=date(2025, 10, 1),
            last_charged_on=date(2026, 4, 1),
            confidence=90,
        )
    )
    db.commit()

    r = reports.year_in_review(db, household.id, 2026)

    assert r.total_in == Decimal("3000.00")
    assert r.total_out == Decimal("550.00")
    assert r.savings_rate == (Decimal("2450.00") / Decimal("3000.00") * 100)
    assert r.biggest_category == "Electronics"
    assert r.biggest_category_amount == Decimal("500.00")
    assert r.biggest_transaction_merchant == "APPLE STORE"
    assert r.biggest_transaction_amount == Decimal("500.00")
    assert r.new_subscriptions == ["Netflix"]
    assert r.cancelled_subscriptions == ["Gym"]
    assert r.net_worth_delta is None  # no snapshots recorded in this test


def test_year_in_review_net_worth_delta_uses_recorded_snapshots(db, household, account):
    db.add_all(
        [
            BalanceSnapshot(
                household_id=household.id, account_id=account.id,
                captured_on=date(2026, 1, 1), balance=Decimal("1000.00"),
            ),
            BalanceSnapshot(
                household_id=household.id, account_id=account.id,
                captured_on=date(2026, 6, 1), balance=Decimal("1500.00"),
            ),
        ]
    )
    db.commit()

    r = reports.year_in_review(db, household.id, 2026)
    assert r.net_worth_delta == Decimal("500.00")
```

Append to `backend/tests/test_reports.py`:

```python
def test_year_in_review_endpoint(client, db, household, account):
    db.add(Transaction(
        household_id=household.id, account_id=account.id,
        posted_at=datetime(2026, 1, 15, tzinfo=UTC), amount=Decimal("1000.00"),
        currency="USD", merchant_raw="PAYCHECK",
    ))
    db.commit()

    res = client.get("/reports/year-in-review?year=2026")
    assert res.status_code == 200
    assert res.json()["total_in"] == "1000.00"


def test_income_vs_expense_endpoint_default_is_twelve_months(client, db):
    res = client.get("/reports/income-vs-expense")
    assert res.status_code == 200
    assert len(res.json()) == 12
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_reports.py -v`
Expected: FAIL — `AttributeError: module 'app.services.reports' has no attribute 'income_vs_expense'`

- [ ] **Step 3: Implement**

Append to `backend/app/services/reports.py`:

```python
from dataclasses import field

from app.models.recurring import RecurringSeries, SeriesStatus
from app.services.snapshots import net_worth_series


@dataclass
class MonthFlow:
    month: str
    income: Decimal
    expense: Decimal
    net: Decimal


def _shift_month(d: date, delta: int) -> date:
    idx = d.year * 12 + (d.month - 1) + delta
    return date(idx // 12, idx % 12 + 1, 1)


def income_vs_expense(db: Session, household_id: uuid.UUID, months: int = 12) -> list[MonthFlow]:
    """Every month in the trailing window, even one with zero transactions."""
    today = datetime.now(UTC).date()
    start_month = _shift_month(date(today.year, today.month, 1), -(months - 1))
    since = datetime.combine(start_month, time.min, tzinfo=UTC)

    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id, Transaction.posted_at >= since
            )
        )
    )
    income: dict[str, Decimal] = defaultdict(Decimal)
    expense: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        k = t.posted_at.strftime("%Y-%m")
        if t.amount >= 0:
            income[k] += t.amount
        else:
            expense[k] += -t.amount

    out = []
    for i in range(months):
        k = _shift_month(start_month, i).strftime("%Y-%m")
        inc = income.get(k, Decimal(0))
        exp = expense.get(k, Decimal(0))
        out.append(MonthFlow(month=k, income=inc, expense=exp, net=inc - exp))
    return out


@dataclass
class YearInReview:
    year: int
    total_in: Decimal
    total_out: Decimal
    savings_rate: Decimal | None
    biggest_category: str | None
    biggest_category_amount: Decimal | None
    biggest_transaction_merchant: str | None
    biggest_transaction_amount: Decimal | None
    new_subscriptions: list[str] = field(default_factory=list)
    cancelled_subscriptions: list[str] = field(default_factory=list)
    net_worth_delta: Decimal | None = None


def _net_worth_delta(db: Session, household_id: uuid.UUID, year: int) -> Decimal | None:
    """Reuses `snapshots.net_worth_series` rather than re-deriving net worth here —
    daily balance snapshots are already this app's source of truth for history
    (design spec §3)."""
    today = datetime.now(UTC).date()
    year_start = date(year, 1, 1)
    if today < year_start:
        return None
    days = (today - year_start).days + 1
    in_year = [p for p in net_worth_series(db, household_id, days=days) if year_start <= p.on <= date(year, 12, 31)]
    if len(in_year) < 2:
        return None
    return in_year[-1].net - in_year[0].net


def year_in_review(db: Session, household_id: uuid.UUID, year: int) -> YearInReview:
    since = datetime(year, 1, 1, tzinfo=UTC)
    until = datetime(year + 1, 1, 1, tzinfo=UTC)
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.posted_at >= since,
                Transaction.posted_at < until,
            )
        )
    )
    total_in = sum((t.amount for t in txns if t.amount >= 0), Decimal(0))
    total_out = sum((-t.amount for t in txns if t.amount < 0), Decimal(0))
    savings_rate = ((total_in - total_out) / total_in * 100) if total_in else None

    buckets = spending(db, household_id, date(year, 1, 1), date(year, 12, 31), "category")
    biggest_category = buckets[0].key if buckets else None
    biggest_category_amount = buckets[0].total if buckets else None

    outflows = [t for t in txns if t.amount < 0]
    biggest_txn = min(outflows, key=lambda t: t.amount) if outflows else None

    series = list(db.scalars(select(RecurringSeries).where(RecurringSeries.household_id == household_id)))
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    new_subs = sorted(s.label for s in series if year_start <= s.first_charged_on <= year_end)
    # ponytail: RecurringSeries has no `cancelled_at` column (models/recurring.py) — the
    # closest available signal for "cancelled during this year" is the last charge date
    # on a series whose status has since moved off `active`. Add a real timestamp on
    # cancellation if this ever needs to be exact rather than a same-year approximation.
    cancelled_subs = sorted(
        s.label
        for s in series
        if s.status in (SeriesStatus.cancelled, SeriesStatus.ended) and year_start <= s.last_charged_on <= year_end
    )

    return YearInReview(
        year=year,
        total_in=total_in,
        total_out=total_out,
        savings_rate=savings_rate,
        biggest_category=biggest_category,
        biggest_category_amount=biggest_category_amount,
        biggest_transaction_merchant=biggest_txn.merchant_raw if biggest_txn else None,
        biggest_transaction_amount=(-biggest_txn.amount) if biggest_txn else None,
        new_subscriptions=new_subs,
        cancelled_subscriptions=cancelled_subs,
        net_worth_delta=_net_worth_delta(db, household_id, year),
    )
```

Move the new `from dataclasses import field` up into the existing `from dataclasses import dataclass` line (`from dataclasses import dataclass, field`) rather than leaving a second import statement mid-file.

Append to `backend/app/schemas/report.py`:

```python
class MonthFlowOut(BaseModel):
    month: str
    income: Decimal
    expense: Decimal
    net: Decimal


class YearInReviewOut(BaseModel):
    year: int
    total_in: Decimal
    total_out: Decimal
    savings_rate: Decimal | None
    biggest_category: str | None
    biggest_category_amount: Decimal | None
    biggest_transaction_merchant: str | None
    biggest_transaction_amount: Decimal | None
    new_subscriptions: list[str]
    cancelled_subscriptions: list[str]
    net_worth_delta: Decimal | None
```

Append to `backend/app/api/reports.py`:

```python
from app.schemas.report import MonthFlowOut, YearInReviewOut  # merge into the existing import line


@router.get("/income-vs-expense", response_model=list[MonthFlowOut])
def get_income_vs_expense(
    months: int = 12, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[MonthFlowOut]:
    return [
        MonthFlowOut(month=m.month, income=m.income, expense=m.expense, net=m.net)
        for m in reports.income_vs_expense(db, hid, months)
    ]


@router.get("/year-in-review", response_model=YearInReviewOut)
def get_year_in_review(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> YearInReviewOut:
    r = reports.year_in_review(db, hid, year)
    return YearInReviewOut(
        year=r.year, total_in=r.total_in, total_out=r.total_out, savings_rate=r.savings_rate,
        biggest_category=r.biggest_category, biggest_category_amount=r.biggest_category_amount,
        biggest_transaction_merchant=r.biggest_transaction_merchant,
        biggest_transaction_amount=r.biggest_transaction_amount,
        new_subscriptions=r.new_subscriptions, cancelled_subscriptions=r.cancelled_subscriptions,
        net_worth_delta=r.net_worth_delta,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_reports.py -v`
Expected: PASS — 11 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/reports.py backend/app/schemas/report.py backend/app/api/reports.py \
        backend/tests/test_reports.py
git commit -m "feat: income vs expense and a year-in-review summary"
```

---

### Task 3: Tax — FIFO realized gains

**Files:**
- Create: `backend/app/services/tax.py`
- Create: `backend/app/schemas/tax.py`
- Create: `backend/app/api/tax.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_tax.py`

**Interfaces:**
- Consumes: `Trade`, `TradeType` (`app.models.trade`); `Security` (`app.models.security`).
- Produces:
  - `RealizedGain` dataclass: `security_id`, `symbol`, `account_id`, `opened_on`, `closed_on`, `quantity`, `proceeds`, `cost_basis`, `gain`, `term: str`
  - `RealizedGainsResult` dataclass: `year`, `gains: list[RealizedGain]`, `short_term_gain`, `long_term_gain`, `total_gain`
  - `realized_gains(db, household_id, year: int) -> RealizedGainsResult`
  - Router `tax.router`, prefix `/tax`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tax.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.security import Security
from app.models.trade import Trade, TradeType
from app.services import tax

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Tax Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.investment, name="Brokerage", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def security(db, household):
    row = Security(household_id=household.id, symbol="VTI", name="Vanguard Total Stock", currency="USD")
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


def _trade(household, account, security, **kw):
    base = dict(
        household_id=household.id, account_id=account.id, security_id=security.id,
        fees=Decimal(0), currency="USD",
    )
    base.update(kw)
    return Trade(**base)


def test_fifo_across_partial_sells_and_multiple_lots(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2025, 6, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(20)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(15), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert len(result.gains) == 2
    lot_a, lot_b = result.gains
    # Lot A: bought 2024-01-01, fully consumed by the sale — held > 365 days, long-term.
    assert lot_a.opened_on == date(2024, 1, 1)
    assert lot_a.quantity == Decimal(10)
    assert lot_a.cost_basis == Decimal("100")
    assert lot_a.proceeds == Decimal("300")
    assert lot_a.gain == Decimal("200")
    assert lot_a.term == "long"
    # Lot B: bought 2025-06-01, partially consumed (5 of 10 units) — under 365 days, short-term.
    assert lot_b.opened_on == date(2025, 6, 1)
    assert lot_b.quantity == Decimal(5)
    assert lot_b.cost_basis == Decimal("100")
    assert lot_b.proceeds == Decimal("150")
    assert lot_b.gain == Decimal("50")
    assert lot_b.term == "short"

    assert result.short_term_gain == Decimal("50")
    assert result.long_term_gain == Decimal("200")
    assert result.total_gain == Decimal("250")


def test_realized_gains_for_a_year_with_no_sells(db, household, account, security):
    db.add(
        _trade(household, account, security, traded_on=date(2026, 3, 1), type=TradeType.buy,
               quantity=Decimal(10), price_per_unit=Decimal(10))
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert result.gains == []
    assert result.short_term_gain == Decimal(0)
    assert result.long_term_gain == Decimal(0)
    assert result.total_gain == Decimal(0)


def test_a_split_scales_the_open_lot_without_changing_its_holding_period(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2025, 1, 1), type=TradeType.split,
                   split_ratio=Decimal(2)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(20), price_per_unit=Decimal(8)),
        ]
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert len(result.gains) == 1
    gain = result.gains[0]
    # 10 units @ $10 = $100 total cost; the split doubles units and halves cost/unit,
    # so total cost basis is unchanged at $100 for all 20 post-split units.
    assert gain.cost_basis == Decimal("100")
    assert gain.proceeds == Decimal("160")
    assert gain.gain == Decimal("60")
    # The split doesn't restart the clock — opened_on is still the original buy.
    assert gain.opened_on == date(2024, 1, 1)
    assert gain.term == "long"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_tax.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tax'`

- [ ] **Step 3: Write the FIFO engine**

Create `backend/app/services/tax.py`:

```python
"""FIFO realized-gains engine over the existing trade log (`models/trade.py`). Keyed
per (security_id, account_id), same boundary as `services/portfolio.py`'s average
cost — a separate, from-scratch replay because average cost and lot-by-lot FIFO are
different methods for different questions, not two implementations of one.

Wash-sale detection is cut (design spec, P5) — `export_csv` (Task 4) says so on its
face. This app's `AccountType` (models/account.py) has no taxable-vs-retirement
distinction, so realized gains here cover every sell trade; see this plan's recorded
deviation for why that's a reporting-tool limitation, not a bug.
"""

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import Security
from app.models.trade import Trade, TradeType

LONG_TERM_DAYS = 365


@dataclass
class _Lot:
    quantity: Decimal
    cost_per_unit: Decimal
    opened_on: date


@dataclass
class RealizedGain:
    security_id: uuid.UUID
    symbol: str
    account_id: uuid.UUID
    opened_on: date
    closed_on: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    gain: Decimal
    term: str  # "short" | "long"


@dataclass
class RealizedGainsResult:
    year: int
    gains: list[RealizedGain] = field(default_factory=list)
    short_term_gain: Decimal = Decimal(0)
    long_term_gain: Decimal = Decimal(0)
    total_gain: Decimal = Decimal(0)


def _replay(trades: list[Trade], symbols: dict[uuid.UUID, str]) -> list[RealizedGain]:
    lots: dict[tuple[uuid.UUID, uuid.UUID], deque[_Lot]] = defaultdict(deque)
    gains: list[RealizedGain] = []

    for t in trades:
        key = (t.security_id, t.account_id)

        if t.type == TradeType.buy:
            if not t.quantity:
                continue
            cost_per_unit = (t.quantity * t.price_per_unit + t.fees) / t.quantity
            lots[key].append(_Lot(quantity=t.quantity, cost_per_unit=cost_per_unit, opened_on=t.traded_on))

        elif t.type == TradeType.sell:
            if not t.quantity:
                continue
            proceeds_per_unit = (t.quantity * t.price_per_unit - t.fees) / t.quantity
            remaining = t.quantity
            queue = lots[key]
            while remaining > 0 and queue:
                lot = queue[0]
                take = min(lot.quantity, remaining)
                cost_basis = take * lot.cost_per_unit
                proceeds = take * proceeds_per_unit
                term = "long" if (t.traded_on - lot.opened_on).days > LONG_TERM_DAYS else "short"
                gains.append(
                    RealizedGain(
                        security_id=t.security_id,
                        symbol=symbols.get(t.security_id, "?"),
                        account_id=t.account_id,
                        opened_on=lot.opened_on,
                        closed_on=t.traded_on,
                        quantity=take,
                        proceeds=proceeds,
                        cost_basis=cost_basis,
                        gain=proceeds - cost_basis,
                        term=term,
                    )
                )
                lot.quantity -= take
                remaining -= take
                if lot.quantity == 0:
                    queue.popleft()
            # A sell that outruns every open lot (remaining > 0 here) would mean the
            # trade log itself is inconsistent. trades.py already refuses to write a
            # sell that goes negative (`portfolio.InsufficientUnitsError`), so every
            # sell this function ever sees has enough recorded units to fully match.

        elif t.type == TradeType.split and t.split_ratio:
            # New-per-old, same as portfolio.py: units scale up and cost per unit
            # scales down by the same factor, so total cost basis is unchanged by the
            # split itself, and the lot's opened_on — its holding period — is untouched.
            for lot in lots[key]:
                lot.quantity *= t.split_ratio
                lot.cost_per_unit /= t.split_ratio

        # dividend: no lot effect. Dividend income is covered by `income_summary`
        # (Task 4), from categorized transactions, not from the trade log — see this
        # plan's recorded deviation on why the two sources aren't both read here.

    return gains


def realized_gains(db: Session, household_id: uuid.UUID, year: int) -> RealizedGainsResult:
    trades = list(
        db.scalars(
            select(Trade).where(Trade.household_id == household_id).order_by(Trade.traded_on, Trade.created_at)
        )
    )
    symbols = {s.id: s.symbol for s in db.scalars(select(Security).where(Security.household_id == household_id))}
    all_gains = _replay(trades, symbols)
    year_gains = sorted((g for g in all_gains if g.closed_on.year == year), key=lambda g: g.closed_on)
    short = sum((g.gain for g in year_gains if g.term == "short"), Decimal(0))
    long_ = sum((g.gain for g in year_gains if g.term == "long"), Decimal(0))
    return RealizedGainsResult(year=year, gains=year_gains, short_term_gain=short, long_term_gain=long_, total_gain=short + long_)
```

- [ ] **Step 4: Write the schema and router**

Create `backend/app/schemas/tax.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class RealizedGainOut(BaseModel):
    security_id: uuid.UUID
    symbol: str
    account_id: uuid.UUID
    opened_on: date
    closed_on: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    gain: Decimal
    term: str


class RealizedGainsOut(BaseModel):
    year: int
    gains: list[RealizedGainOut]
    short_term_gain: Decimal
    long_term_gain: Decimal
    total_gain: Decimal
```

Create `backend/app/api/tax.py`:

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.tax import RealizedGainOut, RealizedGainsOut
from app.services import tax

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/realized-gains", response_model=RealizedGainsOut)
def get_realized_gains(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> RealizedGainsOut:
    r = tax.realized_gains(db, hid, year)
    return RealizedGainsOut(
        year=r.year,
        gains=[
            RealizedGainOut(
                security_id=g.security_id, symbol=g.symbol, account_id=g.account_id,
                opened_on=g.opened_on, closed_on=g.closed_on, quantity=g.quantity,
                proceeds=g.proceeds, cost_basis=g.cost_basis, gain=g.gain, term=g.term,
            )
            for g in r.gains
        ],
        short_term_gain=r.short_term_gain, long_term_gain=r.long_term_gain, total_gain=r.total_gain,
    )
```

In `backend/app/main.py`, add `tax` to the `from app.api import (...)` tuple and `app.include_router(tax.router)` alongside the others.

- [ ] **Step 5: Append a router test to the same test file**

Append to `backend/tests/test_tax.py` (the `client` fixture from Step 1 covers this):

```python
def test_realized_gains_endpoint(client, db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    res = client.get("/tax/realized-gains?year=2026")
    assert res.status_code == 200
    body = res.json()
    assert body["total_gain"] == "200"
    assert body["gains"][0]["symbol"] == "VTI"
```

- [ ] **Step 6: Run every test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_tax.py -v`
Expected: PASS.

- [ ] **Step 7: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/tax.py backend/app/schemas/tax.py backend/app/api/tax.py backend/app/main.py \
        backend/tests/test_tax.py
git commit -m "feat: FIFO realized gains over the trade log"
```

---

### Task 4: Tax — income summary and the Schedule-D-shaped export

**Files:**
- Modify: `backend/app/services/tax.py`
- Modify: `backend/app/schemas/tax.py`
- Modify: `backend/app/api/tax.py`
- Test: `backend/tests/test_tax.py` (append)

**Interfaces:**
- Consumes: `system_category_id` (`app.services.categories`); `Transaction` (`app.models.transaction`); `realized_gains` (Task 3).
- Produces:
  - `IncomeSummary` dataclass: `year`, `dividends`, `interest`, `total`
  - `income_summary(db, household_id, year: int) -> IncomeSummary`
  - `WASH_SALE_DISCLAIMER: str`
  - `export_csv(db, household_id, year: int) -> str`
  - Two new routes: `/tax/income-summary`, `/tax/export`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tax.py`:

```python
from datetime import UTC, datetime

from app.models.transaction import Transaction
from app.services.categories import ensure_system_categories, system_category_id


def test_income_summary_reads_dividends_and_interest_from_categorized_transactions(db, household, account):
    ensure_system_categories(db)
    dividends = system_category_id("Income/Dividends")
    interest = system_category_id("Income/Interest")
    db.add_all(
        [
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 3, 1, tzinfo=UTC), amount=Decimal("120.00"),
                        currency="USD", merchant_raw="VTI DIV", category_id=dividends),
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 4, 1, tzinfo=UTC), amount=Decimal("5.00"),
                        currency="USD", merchant_raw="BANK INTEREST", category_id=interest),
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2025, 12, 1, tzinfo=UTC), amount=Decimal("999.00"),
                        currency="USD", merchant_raw="LAST YEAR DIV", category_id=dividends),
        ]
    )
    db.commit()

    summary = tax.income_summary(db, household.id, 2026)

    assert summary.dividends == Decimal("120.00")
    assert summary.interest == Decimal("5.00")
    assert summary.total == Decimal("125.00")


def test_income_summary_ignores_trade_log_dividends(db, household, account, security):
    """Dividends recorded as a Trade row are a different feature's data and are not
    double-counted here — see the plan's recorded deviation on why."""
    db.add(
        _trade(household, account, security, traded_on=date(2026, 3, 1), type=TradeType.dividend,
               quantity=Decimal(0), price_per_unit=Decimal("50.00"))
    )
    db.commit()

    assert tax.income_summary(db, household.id, 2026).total == Decimal(0)


def test_export_csv_discloses_wash_sales_are_not_handled(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    csv_text = tax.export_csv(db, household.id, 2026)

    assert "wash sale" in csv_text.lower()
    assert "advice" not in csv_text.lower()
    assert "VTI" in csv_text
    assert "Short-term total" in csv_text
    assert "Long-term total" in csv_text


def test_export_endpoint_returns_csv(client, db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    res = client.get("/tax/export?year=2026")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "wash sale" in res.text.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_tax.py -v`
Expected: FAIL — `AttributeError: module 'app.services.tax' has no attribute 'income_summary'`

- [ ] **Step 3: Implement**

Append to `backend/app/services/tax.py`:

```python
import csv
import io
from datetime import UTC, datetime

from app.models.transaction import Transaction
from app.services.categories import system_category_id


@dataclass
class IncomeSummary:
    year: int
    dividends: Decimal
    interest: Decimal
    total: Decimal


def income_summary(db: Session, household_id: uuid.UUID, year: int) -> IncomeSummary:
    """Dividends and interest, both read from categorized transactions (P1's system
    taxonomy) rather than from the trade log's own `dividend` TradeType — a household's
    brokerage dividend usually also lands as a bank-fed transaction row, and reading it
    from both places would double it. `realized_gains` above is the only place this
    phase reads `models/trade.py` directly."""
    dividends_id = system_category_id("Income/Dividends")
    interest_id = system_category_id("Income/Interest")
    since = datetime(year, 1, 1, tzinfo=UTC)
    until = datetime(year + 1, 1, 1, tzinfo=UTC)

    txns = db.scalars(
        select(Transaction).where(
            Transaction.household_id == household_id,
            Transaction.category_id.in_([dividends_id, interest_id]),
            Transaction.posted_at >= since,
            Transaction.posted_at < until,
        )
    )
    dividends = Decimal(0)
    interest = Decimal(0)
    for t in txns:
        if t.category_id == dividends_id:
            dividends += t.amount
        elif t.category_id == interest_id:
            interest += t.amount
    return IncomeSummary(year=year, dividends=dividends, interest=interest, total=dividends + interest)


WASH_SALE_DISCLAIMER = (
    "This export does not detect or adjust for wash sales. If a security was sold at a "
    "loss and a substantially identical one bought within 30 days, the real deductible "
    "loss may be lower than the figure below. This is a reporting tool, not tax advice — "
    "confirm with a tax professional before filing."
)


def export_csv(db: Session, household_id: uuid.UUID, year: int) -> str:
    """A Schedule-D-shaped CSV: one row per matched lot, then short/long totals. A
    starting point to paste from, not a filing document."""
    result = realized_gains(db, household_id, year)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f"# {WASH_SALE_DISCLAIMER}"])
    writer.writerow(
        ["Symbol", "Account", "Date acquired", "Date sold", "Proceeds", "Cost basis", "Gain/loss", "Term"]
    )
    for g in result.gains:
        writer.writerow(
            [g.symbol, str(g.account_id), g.opened_on.isoformat(), g.closed_on.isoformat(),
             str(g.proceeds), str(g.cost_basis), str(g.gain), g.term]
        )
    writer.writerow([])
    writer.writerow(["Short-term total", str(result.short_term_gain)])
    writer.writerow(["Long-term total", str(result.long_term_gain)])
    writer.writerow(["Total", str(result.total_gain)])
    return out.getvalue()
```

Note `import csv`, `import io`, and `from datetime import UTC, datetime` land at the top of the module alongside the existing imports rather than mid-file; `from app.models.transaction import Transaction` and `from app.services.categories import system_category_id` do the same.

Append to `backend/app/schemas/tax.py`:

```python
class IncomeSummaryOut(BaseModel):
    year: int
    dividends: Decimal
    interest: Decimal
    total: Decimal
```

Append to `backend/app/api/tax.py`:

```python
from fastapi.responses import Response

from app.schemas.tax import IncomeSummaryOut  # merge into the existing import line


@router.get("/income-summary", response_model=IncomeSummaryOut)
def get_income_summary(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> IncomeSummaryOut:
    s = tax.income_summary(db, hid, year)
    return IncomeSummaryOut(year=s.year, dividends=s.dividends, interest=s.interest, total=s.total)


@router.get("/export")
def get_tax_export(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> Response:
    csv_text = tax.export_csv(db, hid, year)
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="realized-gains-{year}.csv"'},
    )
```

- [ ] **Step 4: Run every test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_tax.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/tax.py backend/app/schemas/tax.py backend/app/api/tax.py \
        backend/tests/test_tax.py
git commit -m "feat: dividend and interest income summary, and a CSV that says what it skips"
```

---

### Task 5: Vault — the `Document` model, `accounts.beneficiary`, and the phase's one migration

**Files:**
- Create: `backend/app/models/document.py`
- Modify: `backend/app/models/account.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/account.py`
- Modify: `backend/app/services/accounts.py`
- Modify: `backend/app/core/config.py`
- Modify: `docker-compose.yml`
- Create: `backend/migrations/versions/b7e4a591c3d0_documents_and_beneficiary.py`
- Test: `backend/tests/test_documents.py`, `backend/tests/test_accounts.py` (append)

**Interfaces:**
- Produces:
  - `DocumentKind` enum: `will | trust | insurance | deed | title | statement | other`
  - `Document` model — see columns below
  - `Account.beneficiary: Mapped[str | None]`
  - `settings.documents_dir: str`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_documents.py`:

```python
import uuid

import pytest

from app.models.document import Document, DocumentKind
from app.models.household import Household


@pytest.fixture
def household(db):
    row = Household(name="Vault Household")
    db.add(row)
    db.commit()
    return row


def test_document_round_trips_every_column(db, household):
    doc = Document(
        household_id=household.id,
        kind=DocumentKind.will,
        title="My Will",
        filename="will.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        ciphertext_path="/data/documents/x/y.enc",
        notes="Signed 2026",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    fetched = db.get(Document, doc.id)
    assert fetched is not None
    assert fetched.kind == DocumentKind.will
    assert fetched.title == "My Will"
    assert fetched.filename == "will.pdf"
    assert fetched.content_type == "application/pdf"
    assert fetched.size_bytes == 1234
    assert fetched.ciphertext_path == "/data/documents/x/y.enc"
    assert fetched.notes == "Signed 2026"
    assert fetched.created_at is not None


def test_document_notes_is_optional(db, household):
    doc = Document(
        household_id=household.id, kind=DocumentKind.other, title="Misc", filename="x.txt",
        content_type="text/plain", size_bytes=1, ciphertext_path="/tmp/x.enc",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    assert doc.notes is None
```

Append to `backend/tests/test_accounts.py`:

```python
def test_beneficiary_round_trips(db):
    from app.models.household import Household

    household = Household(name="Beneficiary Household")
    db.add(household)
    db.commit()

    acct = accounts.create(
        db, household.id, AccountCreate(type="investment", name="IRA", beneficiary="Jane Doe")
    )
    assert acct.beneficiary == "Jane Doe"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py tests/test_accounts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.document'`, then `TypeError: AccountCreate() got an unexpected keyword argument 'beneficiary'`

- [ ] **Step 3: Write the model**

Create `backend/app/models/document.py`:

```python
import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentKind(str, enum.Enum):
    will = "will"
    trust = "trust"
    insurance = "insurance"
    deed = "deed"
    title = "title"
    statement = "statement"
    other = "other"


class Document(Base, UUIDMixin, TimestampMixin):
    """Metadata for one encrypted file in the household's vault.

    The file itself never touches this row or this database — only its encrypted
    bytes on disk do. `ciphertext_path` names a file under `settings.documents_dir`
    holding exactly the blob `app.core.encryption.encrypt()` returns: a wrapped DEK
    and the AES-GCM-sealed file body, the same envelope provider credentials use
    (`app/providers/base.py`). No separate `nonce`/`wrapped_key` columns — the real
    encryption module exposes one `encrypt`/`decrypt` pair over one opaque blob, not a
    lower-level API split into parts; see this plan's recorded deviation for why.
    """

    __tablename__ = "documents"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind, name="document_kind"))
    title: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    ciphertext_path: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
```

Add to `backend/app/models/__init__.py`, alongside the existing imports:

```python
from app.models.document import Document, DocumentKind  # noqa: F401
```

In `backend/app/models/account.py`, add one column to `Account`:

```python
    # Estate readiness (P5): who receives this account. One string, not a table — a
    # beneficiary record here is a name, not a legal document, until there's a reason
    # for more.
    beneficiary: Mapped[str | None] = mapped_column(nullable=True)
```

- [ ] **Step 4: Wire `beneficiary` through the account schemas and service**

In `backend/app/schemas/account.py`, add `beneficiary: str | None = None` to `AccountCreate`, `AccountOut`, and `AccountUpdate` (matching the existing `institution` field's shape in each).

In `backend/app/services/accounts.py::create`, add `beneficiary=data.beneficiary` to the `Account(...)` constructor call. `update` needs no change — its existing `data.model_dump(exclude_unset=True, exclude_none=True)` / `setattr` loop already carries any new schema field through automatically, the same way it already does for `institution`.

- [ ] **Step 5: Add the setting and the compose volume**

In `backend/app/core/config.py`, add to `Settings`:

```python
    # Document vault (P5). Files are encrypted before they ever touch disk (see
    # app/services/documents.py) — this only says where the encrypted blobs live.
    # Compose mounts a named volume here so they survive a container recreate.
    documents_dir: str = "./data/documents"
```

In `docker-compose.yml`, add a `volumes` line to the `api` service (alongside its existing `ports`/`depends_on`/`command`):

```yaml
    volumes: ["documents-data:/app/data/documents"]
```

and register the volume at the bottom, alongside `pgdata`:

```yaml
volumes:
  pgdata:
  documents-data:
```

- [ ] **Step 6: Write the migration**

Find the current head: `cd backend && .venv/Scripts/python -m alembic heads`. At time of writing that is `e1f3a2c4b508`; use whatever the command reports.

Create `backend/migrations/versions/b7e4a591c3d0_documents_and_beneficiary.py`:

```python
"""documents (encrypted vault) and accounts.beneficiary

Revision ID: b7e4a591c3d0
Revises: e1f3a2c4b508
Create Date: 2026-08-01

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e4a591c3d0"
down_revision: Union[str, Sequence[str], None] = "e1f3a2c4b508"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

document_kind = postgresql.ENUM(
    "will", "trust", "insurance", "deed", "title", "statement", "other",
    name="document_kind", create_type=False,
)


def upgrade() -> None:
    document_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", document_kind, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("ciphertext_path", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_household_id"), "documents", ["household_id"])
    op.add_column("accounts", sa.Column("beneficiary", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "beneficiary")
    op.drop_index(op.f("ix_documents_household_id"), table_name="documents")
    op.drop_table("documents")
    # Postgres does not drop an enum with its table — same fix as every prior migration.
    document_kind.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 7: Run every test to verify it passes, then the migration round trip**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py tests/test_accounts.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 8: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/models/document.py backend/app/models/account.py backend/app/models/__init__.py \
        backend/app/schemas/account.py backend/app/services/accounts.py backend/app/core/config.py \
        backend/migrations/versions/b7e4a591c3d0_documents_and_beneficiary.py \
        backend/tests/test_documents.py backend/tests/test_accounts.py docker-compose.yml
git commit -m "feat: a documents table and a beneficiary field, one migration for the phase"
```

---

### Task 6: Vault — envelope-encrypted file storage

**Files:**
- Create: `backend/app/services/documents.py`
- Test: `backend/tests/test_documents.py` (append)

**Interfaces:**
- Consumes: `encrypt`, `decrypt` (`app.core.encryption`); `Document`, `DocumentKind` (Task 5).
- Produces:
  - `class DocumentNotFound(Exception)`
  - `save(db, household_id, *, kind, title, filename, content_type, data: bytes, notes=None) -> Document`
  - `get(db, household_id, document_id) -> Document | None`
  - `list_for(db, household_id) -> list[Document]`
  - `read_plaintext(db, household_id, document_id) -> bytes` — raises `DocumentNotFound`
  - `delete(db, household_id, document_id) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_documents.py`:

```python
from pathlib import Path

from app.core.config import settings
from app.services import documents


@pytest.fixture
def other_household(db):
    row = Household(name="Other Vault Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture(autouse=True)
def _isolated_documents_dir(tmp_path, monkeypatch):
    # Every test in this file gets its own throwaway directory — never the real
    # ./data/documents a running install would use.
    monkeypatch.setattr(settings, "documents_dir", str(tmp_path))


def test_upload_download_round_trip_is_byte_identical(db, household):
    plaintext = b"this is the whole will, byte for byte"
    doc = documents.save(
        db, household.id, kind=DocumentKind.will, title="My Will", filename="will.txt",
        content_type="text/plain", data=plaintext,
    )

    recovered = documents.read_plaintext(db, household.id, doc.id)
    assert recovered == plaintext


def test_ciphertext_on_disk_is_not_the_plaintext(db, household):
    plaintext = b"a secret only the household should ever read in the clear"
    doc = documents.save(
        db, household.id, kind=DocumentKind.other, title="Secret", filename="s.txt",
        content_type="text/plain", data=plaintext,
    )

    raw = Path(doc.ciphertext_path).read_bytes()
    assert raw != plaintext
    assert plaintext not in raw


def test_a_document_from_another_household_is_not_reachable(db, household, other_household):
    doc = documents.save(
        db, household.id, kind=DocumentKind.will, title="My Will", filename="w.txt",
        content_type="text/plain", data=b"private",
    )

    assert documents.get(db, other_household.id, doc.id) is None
    with pytest.raises(documents.DocumentNotFound):
        documents.read_plaintext(db, other_household.id, doc.id)


def test_list_for_is_scoped_and_newest_first(db, household):
    first = documents.save(db, household.id, kind=DocumentKind.other, title="First",
                            filename="a.txt", content_type="text/plain", data=b"a")
    second = documents.save(db, household.id, kind=DocumentKind.other, title="Second",
                             filename="b.txt", content_type="text/plain", data=b"b")

    rows = documents.list_for(db, household.id)
    assert [r.id for r in rows] == [second.id, first.id]


def test_delete_removes_the_row_and_the_file(db, household):
    doc = documents.save(db, household.id, kind=DocumentKind.other, title="Gone",
                          filename="g.txt", content_type="text/plain", data=b"x")
    path = Path(doc.ciphertext_path)
    assert path.exists()

    assert documents.delete(db, household.id, doc.id) is True
    assert documents.get(db, household.id, doc.id) is None
    assert not path.exists()


def test_delete_of_unknown_document_returns_false(db, household):
    assert documents.delete(db, household.id, uuid.uuid4()) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.documents'`

- [ ] **Step 3: Write the service**

Create `backend/app/services/documents.py`:

```python
"""The document vault. Files are encrypted with the same AES-GCM envelope provider
credentials use (`app/core/encryption.py`, `app/providers/base.py`) — read into
memory, sealed once with `encrypt()`, written to disk as one opaque blob under
`settings.documents_dir/<household_id>/<document_id>.enc`. Plaintext exists only for
the duration of an upload or a download, never on disk.

ponytail: whole-file encrypt/decrypt, no streaming/chunked AEAD — a will or an
insurance PDF is a few megabytes, well within what the provider-credentials blob
already proves out. Move to chunked AEAD if uploads ever need to cover something
video-sized.
"""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.encryption import decrypt, encrypt
from app.models.document import Document, DocumentKind


class DocumentNotFound(Exception):
    """A document id that doesn't resolve for this household — missing, or another
    household's row. The router turns this into a 404, never a 500."""


def _aad(household_id: uuid.UUID, document_id: uuid.UUID) -> bytes:
    # Bound to the document's own id, not just the household — swapping one
    # document's ciphertext onto another row in the same household still fails to
    # decrypt, the same defense-in-depth `providers/base.py::_context_aad` gives a
    # provider connection.
    return f"{household_id}:document:{document_id}".encode()


def _path_for(household_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    directory = Path(settings.documents_dir) / str(household_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{document_id}.enc"


def save(
    db: Session,
    household_id: uuid.UUID,
    *,
    kind: DocumentKind,
    title: str,
    filename: str,
    content_type: str,
    data: bytes,
    notes: str | None = None,
) -> Document:
    doc = Document(
        household_id=household_id, kind=kind, title=title, filename=filename,
        content_type=content_type, size_bytes=len(data), ciphertext_path="", notes=notes,
    )
    db.add(doc)
    db.flush()  # assigns doc.id (UUIDMixin's client-side default) without committing —
    # the AAD binds to that id, so the id has to exist before the file is sealed.

    path = _path_for(household_id, doc.id)
    path.write_bytes(encrypt(data, aad=_aad(household_id, doc.id)))
    doc.ciphertext_path = str(path)

    db.commit()
    db.refresh(doc)
    return doc


def get(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    return db.scalar(
        select(Document).where(Document.id == document_id, Document.household_id == household_id)
    )


def list_for(db: Session, household_id: uuid.UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.household_id == household_id).order_by(Document.created_at.desc())
        )
    )


def read_plaintext(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> bytes:
    """Decrypt for a download. Raises DocumentNotFound for a missing id or a foreign
    household's — the same row a caller couldn't `get()` either."""
    doc = get(db, household_id, document_id)
    if doc is None:
        raise DocumentNotFound(str(document_id))
    blob = Path(doc.ciphertext_path).read_bytes()
    return decrypt(blob, aad=_aad(household_id, doc.id))


def delete(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    doc = get(db, household_id, document_id)
    if doc is None:
        return False
    Path(doc.ciphertext_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/documents.py backend/tests/test_documents.py
git commit -m "feat: encrypt vault files at rest with the provider-credential envelope"
```

---

### Task 7: Vault — upload, download, list, delete API

**Files:**
- Create: `backend/app/schemas/document.py`
- Create: `backend/app/api/documents.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_documents.py` (append)

**Interfaces:**
- Consumes: `documents.save/get/list_for/read_plaintext/delete` (Task 6); `DocumentKind` (Task 5).
- Produces:
  - `DocumentOut` schema
  - Router `documents.router`, prefix `/documents`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_documents.py` — the `household`, `other_household`, and `_isolated_documents_dir` fixtures Task 6 already put in this file cover the tests below too; only the `client` fixture is new:

```python
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app

app.state.limiter.enabled = False


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _upload(client, content=b"the whole document, byte for byte"):
    return client.post(
        "/documents",
        data={"kind": "will", "title": "My Will", "notes": "Signed 2026"},
        files={"file": ("will.pdf", content, "application/pdf")},
    )


def test_upload_then_list(client):
    res = _upload(client)
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "will"
    assert body["title"] == "My Will"
    assert body["size_bytes"] == len(b"the whole document, byte for byte")

    listed = client.get("/documents").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_download_round_trips_byte_identical(client):
    content = b"the whole document, byte for byte"
    uploaded = _upload(client, content).json()

    res = client.get(f"/documents/{uploaded['id']}/download")
    assert res.status_code == 200
    assert res.content == content
    assert res.headers["content-type"] == "application/pdf"


def test_delete_then_download_404s(client):
    uploaded = _upload(client).json()
    assert client.delete(f"/documents/{uploaded['id']}").status_code == 200
    assert client.get(f"/documents/{uploaded['id']}/download").status_code == 404


def test_a_document_from_another_household_is_not_downloadable(db, household, other_household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    mine = TestClient(app)
    uploaded = _upload(mine).json()

    app.dependency_overrides[require_household] = lambda: other_household.id
    theirs = TestClient(app)
    res = theirs.get(f"/documents/{uploaded['id']}/download")
    assert res.status_code == 404

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_unknown_document_download_is_404(client):
    assert client.get(f"/documents/{uuid.uuid4()}/download").status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py -v`
Expected: FAIL — 404 on every route (no router mounted yet).

- [ ] **Step 3: Write the schema and router**

Create `backend/app/schemas/document.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentKind


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    title: str
    filename: str
    content_type: str
    size_bytes: int
    notes: str | None
    created_at: datetime
    model_config = {"from_attributes": True}
```

Create `backend/app/api/documents.py`:

```python
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.document import Document, DocumentKind
from app.schemas.document import DocumentOut
from app.services import documents

router = APIRouter(prefix="/documents", tags=["documents"])


def _out(doc: Document) -> DocumentOut:
    return DocumentOut.model_validate(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[DocumentOut]:
    return [_out(d) for d in documents.list_for(db, hid)]


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    kind: DocumentKind = Form(...),
    title: str = Form(...),
    notes: str | None = Form(None),
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> DocumentOut:
    data = await file.read()
    doc = documents.save(
        db, hid, kind=kind, title=title, filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream", data=data, notes=notes,
    )
    return _out(doc)


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> Response:
    doc = documents.get(db, hid, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = documents.read_plaintext(db, hid, document_id)
    except documents.DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(
        content=data, media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not documents.delete(db, hid, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "ok"}
```

In `backend/app/main.py`, add `documents` to the `from app.api import (...)` tuple and `app.include_router(documents.router)` alongside the others.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_documents.py -v`
Expected: PASS — 15 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/schemas/document.py backend/app/api/documents.py backend/app/main.py \
        backend/tests/test_documents.py
git commit -m "feat: upload, download, list, and delete for the document vault"
```

---

### Task 8: Estate readiness checklist

**Files:**
- Create: `backend/app/services/estate.py`
- Create: `backend/app/schemas/estate.py`
- Create: `backend/app/api/estate.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_estate.py`

**Interfaces:**
- Consumes: `Account`, `AccountType` (`app.models.account`); `Document`, `DocumentKind` (Task 5).
- Produces:
  - `ChecklistItem` dataclass: `label`, `satisfied: bool`, `detail: str`
  - `Checklist` dataclass: `items: list[ChecklistItem]`, `gaps: int` (property)
  - `checklist(db, household_id) -> Checklist`
  - Router `estate.router`, prefix `/estate`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_estate.py`:

```python
import pytest

from app.models.account import Account, AccountType
from app.models.document import Document, DocumentKind
from app.models.household import Household
from app.services import estate


@pytest.fixture
def household(db):
    row = Household(name="Estate Household")
    db.add(row)
    db.commit()
    return row


def test_checklist_reports_every_gap_when_nothing_is_set_up(db, household):
    db.add(Account(household_id=household.id, type=AccountType.investment, name="401k", currency="USD"))
    db.commit()

    result = estate.checklist(db, household.id)

    by_label = {i.label: i for i in result.items}
    assert by_label["Will on file"].satisfied is False
    assert by_label["Beneficiary on every retirement/insurance account"].satisfied is False
    assert result.gaps >= 2


def test_checklist_is_satisfied_once_a_will_and_beneficiaries_are_on_file(db, household):
    acct = Account(
        household_id=household.id, type=AccountType.investment, name="401k", currency="USD",
        beneficiary="Jane Doe",
    )
    db.add(acct)
    db.add(
        Document(
            household_id=household.id, kind=DocumentKind.will, title="Will", filename="w.pdf",
            content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/w.enc",
        )
    )
    db.commit()

    result = estate.checklist(db, household.id)
    by_label = {i.label: i for i in result.items}
    assert by_label["Will on file"].satisfied is True
    assert by_label["Beneficiary on every retirement/insurance account"].satisfied is True


def test_checklist_flags_a_missing_beneficiary_on_one_of_several_accounts(db, household):
    db.add_all(
        [
            Account(household_id=household.id, type=AccountType.investment, name="IRA",
                    currency="USD", beneficiary="Jane Doe"),
            Account(household_id=household.id, type=AccountType.investment, name="401k",
                    currency="USD", beneficiary=None),
        ]
    )
    db.commit()

    result = estate.checklist(db, household.id)
    item = next(i for i in result.items if i.label == "Beneficiary on every retirement/insurance account")
    assert item.satisfied is False
    assert "401k" in item.detail


def test_checklist_deed_check_compares_counts_of_property_accounts_to_deed_documents(db, household):
    db.add_all(
        [
            Account(household_id=household.id, type=AccountType.asset, name="Rental House", currency="USD"),
            Account(household_id=household.id, type=AccountType.asset, name="Cabin", currency="USD"),
        ]
    )
    db.commit()

    no_deeds = estate.checklist(db, household.id)
    deed_item = next(i for i in no_deeds.items if "Deed" in i.label)
    assert deed_item.satisfied is False

    db.add(
        Document(household_id=household.id, kind=DocumentKind.deed, title="Rental deed",
                 filename="d1.pdf", content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/d1.enc")
    )
    db.add(
        Document(household_id=household.id, kind=DocumentKind.title, title="Cabin title",
                 filename="d2.pdf", content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/d2.enc")
    )
    db.commit()

    now_satisfied = estate.checklist(db, household.id)
    deed_item = next(i for i in now_satisfied.items if "Deed" in i.label)
    assert deed_item.satisfied is True


def test_checklist_with_no_property_accounts_is_satisfied_by_default(db, household):
    result = estate.checklist(db, household.id)
    deed_item = next(i for i in result.items if "Deed" in i.label)
    assert deed_item.satisfied is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_estate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.estate'`

- [ ] **Step 3: Write the service**

Create `backend/app/services/estate.py`:

```python
"""Estate readiness checklist — a computed read, no storage of its own. It reports
gaps against three questions Origin's "estate planning" pillar asks: is there a will
on file, does every retirement/insurance account carry a beneficiary, is there a deed
for every property account. It never drafts a will or a beneficiary form — that's
explicitly cut (design spec, P5) — it only reports what's missing.

`AccountType` (models/account.py) has nine values and none of them is `retirement`,
`insurance`, or `property` — the closest fits are `investment` (something that names
a beneficiary) and `asset` (something a deed attaches to). Both choices are named
here, not silently assumed; see this plan's recorded deviations for the reasoning.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.document import Document, DocumentKind


@dataclass
class ChecklistItem:
    label: str
    satisfied: bool
    detail: str


@dataclass
class Checklist:
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def gaps(self) -> int:
        return sum(1 for i in self.items if not i.satisfied)


def checklist(db: Session, household_id: uuid.UUID) -> Checklist:
    items: list[ChecklistItem] = []

    has_will = (
        db.scalar(
            select(Document.id).where(Document.household_id == household_id, Document.kind == DocumentKind.will)
        )
        is not None
    )
    items.append(
        ChecklistItem(
            label="Will on file",
            satisfied=has_will,
            detail="Uploaded to the vault." if has_will else "No will uploaded to the vault yet.",
        )
    )

    retirement_accounts = list(
        db.scalars(
            select(Account).where(Account.household_id == household_id, Account.type == AccountType.investment)
        )
    )
    missing_beneficiary = [a for a in retirement_accounts if not a.beneficiary]
    items.append(
        ChecklistItem(
            label="Beneficiary on every retirement/insurance account",
            satisfied=len(missing_beneficiary) == 0,
            detail=(
                "All set." if not missing_beneficiary
                else f"Missing on: {', '.join(a.name for a in missing_beneficiary)}"
            ),
        )
    )

    property_accounts = list(
        db.scalars(select(Account).where(Account.household_id == household_id, Account.type == AccountType.asset))
    )
    # No account_id on `documents` (the spec's own schema doesn't add one), so this can
    # only compare counts, not confirm which specific property a deed belongs to — see
    # this plan's recorded deviation.
    deed_count = len(
        list(
            db.scalars(
                select(Document).where(
                    Document.household_id == household_id,
                    Document.kind.in_([DocumentKind.deed, DocumentKind.title]),
                )
            )
        )
    )
    deed_satisfied = not property_accounts or deed_count >= len(property_accounts)
    items.append(
        ChecklistItem(
            label="Deed on file for every property account",
            satisfied=deed_satisfied,
            detail=(
                "No property accounts to check." if not property_accounts
                else "All set." if deed_satisfied
                else f"{deed_count} deed/title document(s) on file for {len(property_accounts)} property account(s)."
            ),
        )
    )

    return Checklist(items=items)
```

- [ ] **Step 4: Write the schema and router**

Create `backend/app/schemas/estate.py`:

```python
from pydantic import BaseModel


class ChecklistItemOut(BaseModel):
    label: str
    satisfied: bool
    detail: str


class ChecklistOut(BaseModel):
    items: list[ChecklistItemOut]
    gaps: int
```

Create `backend/app/api/estate.py`:

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.estate import ChecklistItemOut, ChecklistOut
from app.services import estate

router = APIRouter(prefix="/estate", tags=["estate"])


@router.get("/checklist", response_model=ChecklistOut)
def get_checklist(hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)) -> ChecklistOut:
    result = estate.checklist(db, hid)
    return ChecklistOut(
        items=[ChecklistItemOut(label=i.label, satisfied=i.satisfied, detail=i.detail) for i in result.items],
        gaps=result.gaps,
    )
```

In `backend/app/main.py`, add `estate` to the `from app.api import (...)` tuple and `app.include_router(estate.router)` alongside the others.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_estate.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 6: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/estate.py backend/app/schemas/estate.py backend/app/api/estate.py \
        backend/app/main.py backend/tests/test_estate.py
git commit -m "feat: a computed estate readiness checklist, no storage of its own"
```

---

### Task 9: Export — every table, one CSV each

**Files:**
- Create: `backend/app/services/export.py`
- Create: `backend/app/api/export.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `Base` (`app.models.base`); the full `app.models` import for registry completeness.
- Produces:
  - `EXCLUDED_TABLES: set[str]`
  - `build_zip(db, household_id) -> bytes`
  - Router `export.router`, prefix `/export`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_export.py`:

```python
import io
import uuid
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  ensure the full registry is populated
from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.base import Base
from app.models.household import Household
from app.models.transaction import Transaction

app.state.limiter.enabled = False

# Hardcoded independently of `app.services.export.EXCLUDED_TABLES` on purpose — a new
# household-scoped model must be consciously routed to a CSV or added to *both* lists
# with a stated reason, not silently inherited by whichever list already exists.
EXPECTED_EXCLUDED_TABLES = {"users", "provider_connections"}


@pytest.fixture
def household(db):
    row = Household(name="Export Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def other_household(db):
    row = Household(name="Other Export Household")
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


def test_export_contains_a_csv_for_every_household_owned_table(client, db, household):
    all_household_tables = {
        name for name, table in Base.metadata.tables.items() if "household_id" in table.columns
    }
    expected_csvs = all_household_tables - EXPECTED_EXCLUDED_TABLES

    res = client.get("/export/all.zip")
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = {n[:-4] for n in zf.namelist() if n.endswith(".csv")}
    assert names == expected_csvs


def test_export_contains_only_the_requesting_household_rows(client, db, household, other_household):
    account = Account(household_id=household.id, type=AccountType.checking, name="Mine", currency="USD")
    other_account = Account(household_id=other_household.id, type=AccountType.checking, name="Theirs", currency="USD")
    db.add_all([account, other_account])
    db.commit()
    db.add_all(
        [
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 1, 1, tzinfo=UTC), amount=Decimal("-1.00"),
                        currency="USD", merchant_raw="Mine"),
            Transaction(household_id=other_household.id, account_id=other_account.id,
                        posted_at=datetime(2026, 1, 1, tzinfo=UTC), amount=Decimal("-2.00"),
                        currency="USD", merchant_raw="Theirs"),
        ]
    )
    db.commit()

    res = client.get("/export/all.zip")
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    txns_csv = zf.read("transactions.csv").decode()
    assert "Mine" in txns_csv
    assert "Theirs" not in txns_csv
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_export.py -v`
Expected: FAIL — 404 (no router mounted).

- [ ] **Step 3: Write the service**

Create `backend/app/services/export.py`:

```python
"""Every table this household owns, one CSV per table, zipped. Enumerates tables from
`Base.metadata` at runtime rather than a hand-maintained list, so a new model with a
`household_id` column is a fact `test_export.py` can catch rather than a step someone
has to remember to add here.

`users.password_hash` and `provider_connections.encrypted_credentials` both carry a
`household_id` column and would otherwise qualify, but they're credential material,
not financial data — see this plan's recorded deviation for the reasoning.
"""

import csv
import io
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from app.models.base import Base

EXCLUDED_TABLES = {"users", "provider_connections"}


def _household_tables() -> list[Table]:
    return sorted(
        (t for name, t in Base.metadata.tables.items() if "household_id" in t.columns and name not in EXCLUDED_TABLES),
        key=lambda t: t.name,
    )


def _serialize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (Decimal, date, datetime, uuid.UUID)):
        return str(value)
    if hasattr(value, "value"):  # str-backed Enum members
        return str(value.value)
    return str(value)


def build_zip(db: Session, household_id: uuid.UUID) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in _household_tables():
            hid_col = table.c.household_id
            # `is_(None)` matches `categories`' system rows (household_id IS NULL) so a
            # household's export includes the shared taxonomy its own transactions
            # reference by id. Every other table's household_id is NOT NULL at the
            # database level, so this clause is a no-op for all of them.
            rows = db.execute(select(table).where((hid_col == household_id) | hid_col.is_(None))).all()
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow([c.name for c in table.columns])
            for row in rows:
                writer.writerow([_serialize(v) for v in row])
            zf.writestr(f"{table.name}.csv", out.getvalue())
    return buf.getvalue()
```

- [ ] **Step 4: Write the router**

Create `backend/app/api/export.py`:

```python
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.services import export

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/all.zip")
def export_all(hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)) -> Response:
    data = export.build_zip(db, hid)
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="openfinance-export.zip"'},
    )
```

In `backend/app/main.py`, add `export` to the `from app.api import (...)` tuple and `app.include_router(export.router)` alongside the others.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_export.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest`
Expected: all pass. This is the point where every model this phase and every prior phase added is exercised by one export call — a good moment to catch a stray table this plan forgot to route.

- [ ] **Step 7: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/export.py backend/app/api/export.py backend/app/main.py \
        backend/tests/test_export.py
git commit -m "feat: every table the household owns, one CSV per table"
```

---

### Task 10: Frontend — reports and tax hooks, cards, and the Reports page

**Files:**
- Create: `frontend/src/reports.ts`
- Create: `frontend/src/tax.ts`
- Create: `frontend/src/ReportsCards.tsx`
- Create: `frontend/src/ReportsCards.test.tsx`
- Create: `frontend/src/pages/ReportsPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `API_BASE` (`./api/client`); `AreaChart`, `BarChart` (`./charts`); `usd`, `pct` (`./money`); `Card`, `Empty`, `PageHead` (`./ui/Shell`).
- Produces: `useSpending`, `useIncomeVsExpense`, `useYearInReview` (`reports.ts`); `useRealizedGains`, `useIncomeSummary`, `taxExportUrl` (`tax.ts`); `SpendingCard`, `CashFlowCard`, `YearInReviewCard`, `TaxCard` (`ReportsCards.tsx`); `ReportsPage`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/ReportsCards.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { SpendingCard, YearInReviewCard, TaxCard } from "./ReportsCards";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("SpendingCard", () => {
  it("renders a bar per bucket, biggest first", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { key: "Groceries", key_id: "c1", total: "50.00", count: 2 },
      { key: "Coffee", key_id: "c2", total: "5.00", count: 1 },
    ]);
    render(<SpendingCard start="2026-07-01" end="2026-07-31" groupBy="category" />, { wrapper });
    await screen.findByText("Groceries");
    expect(screen.getByText("Coffee")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to report", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<SpendingCard start="2026-07-01" end="2026-07-31" groupBy="category" />, { wrapper });
    await waitFor(() => expect(screen.getByText(/nothing to report/i)).toBeInTheDocument());
  });
});

describe("YearInReviewCard", () => {
  it("shows the year's totals and biggest category", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      year: 2026,
      total_in: "3000.00",
      total_out: "550.00",
      savings_rate: "81.7",
      biggest_category: "Electronics",
      biggest_category_amount: "500.00",
      biggest_transaction_merchant: "APPLE STORE",
      biggest_transaction_amount: "500.00",
      new_subscriptions: ["Netflix"],
      cancelled_subscriptions: ["Gym"],
      net_worth_delta: "1200.00",
    });
    render(<YearInReviewCard year={2026} />, { wrapper });
    await screen.findByText("Electronics");
    expect(screen.getByText("Netflix")).toBeInTheDocument();
    expect(screen.getByText("Gym")).toBeInTheDocument();
  });
});

describe("TaxCard", () => {
  it("shows the wash-sale disclaimer and never the word advice", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path.startsWith("/tax/realized-gains")) {
        return { year: 2026, gains: [], short_term_gain: "0", long_term_gain: "0", total_gain: "0" };
      }
      if (path.startsWith("/tax/income-summary")) {
        return { year: 2026, dividends: "0", interest: "0", total: "0" };
      }
      throw new Error(`unexpected path ${path}`);
    });
    render(<TaxCard year={2026} />, { wrapper });
    await screen.findByText(/wash sale/i);
    expect(screen.queryByText(/advice/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- ReportsCards`
Expected: FAIL — cannot resolve `./ReportsCards`.

- [ ] **Step 3: Write the hooks**

Create `frontend/src/reports.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type GroupBy = "category" | "merchant" | "month";

export type SpendingBucket = { key: string; key_id: string | null; total: string; count: number };
export type MonthFlow = { month: string; income: string; expense: string; net: string };
export type YearInReview = {
  year: number;
  total_in: string;
  total_out: string;
  savings_rate: string | null;
  biggest_category: string | null;
  biggest_category_amount: string | null;
  biggest_transaction_merchant: string | null;
  biggest_transaction_amount: string | null;
  new_subscriptions: string[];
  cancelled_subscriptions: string[];
  net_worth_delta: string | null;
};

export function useSpending(start: string, end: string, groupBy: GroupBy) {
  return useQuery({
    queryKey: ["reports", "spending", start, end, groupBy],
    queryFn: () =>
      apiFetch<SpendingBucket[]>(`/reports/spending?start=${start}&end=${end}&group_by=${groupBy}`),
  });
}

export function useIncomeVsExpense(months = 12) {
  return useQuery({
    queryKey: ["reports", "income-vs-expense", months],
    queryFn: () => apiFetch<MonthFlow[]>(`/reports/income-vs-expense?months=${months}`),
  });
}

export function useYearInReview(year: number) {
  return useQuery({
    queryKey: ["reports", "year-in-review", year],
    queryFn: () => apiFetch<YearInReview>(`/reports/year-in-review?year=${year}`),
  });
}
```

Create `frontend/src/tax.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch, API_BASE } from "./api/client";

export type RealizedGain = {
  security_id: string;
  symbol: string;
  account_id: string;
  opened_on: string;
  closed_on: string;
  quantity: string;
  proceeds: string;
  cost_basis: string;
  gain: string;
  term: "short" | "long";
};

export type RealizedGains = {
  year: number;
  gains: RealizedGain[];
  short_term_gain: string;
  long_term_gain: string;
  total_gain: string;
};

export type IncomeSummary = { year: number; dividends: string; interest: string; total: string };

export function useRealizedGains(year: number) {
  return useQuery({
    queryKey: ["tax", "realized-gains", year],
    queryFn: () => apiFetch<RealizedGains>(`/tax/realized-gains?year=${year}`),
  });
}

export function useIncomeSummary(year: number) {
  return useQuery({
    queryKey: ["tax", "income-summary", year],
    queryFn: () => apiFetch<IncomeSummary>(`/tax/income-summary?year=${year}`),
  });
}

export function taxExportUrl(year: number) {
  return `${API_BASE}/tax/export?year=${year}`;
}
```

- [ ] **Step 4: Write the cards**

Create `frontend/src/ReportsCards.tsx`:

```tsx
import { useState } from "react";
import { BarChart } from "./charts";
import { usd } from "./money";
import type { GroupBy } from "./reports";
import { useIncomeVsExpense, useSpending, useYearInReview } from "./reports";
import { taxExportUrl, useIncomeSummary, useRealizedGains } from "./tax";
import { Card, Empty } from "./ui/Shell";

export function SpendingCard({ start, end, groupBy }: { start: string; end: string; groupBy: GroupBy }) {
  const { data = [], isLoading } = useSpending(start, end, groupBy);
  if (isLoading) return <Empty>Loading…</Empty>;
  if (data.length === 0) return <Empty>Nothing to report for this range.</Empty>;

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Spending by {groupBy}</h2>
      <BarChart bars={data.slice(0, 12).map((b) => ({ label: b.key, value: Number(b.total) }))} />
    </Card>
  );
}

export function CashFlowCard({ months = 12 }: { months?: number }) {
  const { data = [], isLoading } = useIncomeVsExpense(months);
  if (isLoading) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">Income vs. expense</h2>
      <BarChart bars={data.map((m) => ({ label: m.month.slice(5), value: Number(m.net) }))} />
      <p className="mt-4 text-[13px] text-muted">
        Bars are net (income minus expense) per month — a bar below the line is a month
        that spent more than it took in.
      </p>
    </Card>
  );
}

export function YearInReviewCard({ year }: { year: number }) {
  const { data, isLoading } = useYearInReview(year);
  if (isLoading || !data) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">{year} in review</h2>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">Total in</p>
          <p className="tnum mt-2 text-xl text-acid">{usd(data.total_in)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Total out</p>
          <p className="tnum mt-2 text-xl">{usd(data.total_out)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Savings rate</p>
          <p className="tnum mt-2 text-xl">{data.savings_rate ? `${Number(data.savings_rate).toFixed(1)}%` : "—"}</p>
        </div>
        <div className="card p-4">
          <p className="label">Net worth change</p>
          <p className="tnum mt-2 text-xl">{data.net_worth_delta ? usd(data.net_worth_delta) : "—"}</p>
        </div>
      </div>
      {data.biggest_category && (
        <p className="text-[13px] text-muted">
          Biggest category: <span className="text-bone">{data.biggest_category}</span> (
          {usd(data.biggest_category_amount ?? "0")})
        </p>
      )}
      {data.biggest_transaction_merchant && (
        <p className="mt-1 text-[13px] text-muted">
          Biggest single transaction:{" "}
          <span className="text-bone">{data.biggest_transaction_merchant}</span> (
          {usd(data.biggest_transaction_amount ?? "0")})
        </p>
      )}
      {data.new_subscriptions.length > 0 && (
        <p className="mt-1 text-[13px] text-muted">
          New subscriptions: <span className="text-bone">{data.new_subscriptions.join(", ")}</span>
        </p>
      )}
      {data.cancelled_subscriptions.length > 0 && (
        <p className="mt-1 text-[13px] text-muted">
          Cancelled: <span className="text-bone">{data.cancelled_subscriptions.join(", ")}</span>
        </p>
      )}
    </Card>
  );
}

export function TaxCard({ year }: { year: number }) {
  const { data: gains, isLoading: gainsLoading } = useRealizedGains(year);
  const { data: income, isLoading: incomeLoading } = useIncomeSummary(year);

  if (gainsLoading || incomeLoading || !gains || !income) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Tax reporting — {year}</h2>
        <a href={taxExportUrl(year)} className="text-[13px] text-acid">
          Export CSV
        </a>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">Short-term gain</p>
          <p className="tnum mt-2 text-xl">{usd(gains.short_term_gain)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Long-term gain</p>
          <p className="tnum mt-2 text-xl">{usd(gains.long_term_gain)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Dividends</p>
          <p className="tnum mt-2 text-xl">{usd(income.dividends)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Interest</p>
          <p className="tnum mt-2 text-xl">{usd(income.interest)}</p>
        </div>
      </div>

      {gains.gains.length === 0 ? (
        <Empty>No realized sales in {year}.</Empty>
      ) : (
        <table className="w-full">
          <tbody>
            {gains.gains.map((g, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="py-2 text-sm">{g.symbol}</td>
                <td className="py-2 text-[13px] text-muted">{g.closed_on}</td>
                <td className="py-2 text-[13px] text-muted">{g.term}</td>
                <td className="tnum py-2 text-right text-sm">{usd(g.gain)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        This export does not detect or adjust for wash sales — if a security was sold at
        a loss and a substantially identical one bought within 30 days, the real
        deductible loss may be lower than shown here. A reporting tool, not tax advice.
      </p>
    </Card>
  );
}
```

Note the disclaimer paragraph in `TaxCard` reuses the same "wash sale... reporting tool, not tax advice" wording the backend's `WASH_SALE_DISCLAIMER` carries, and, like the backend string, never uses the word "advice" to mean anything is being given — it appears only inside the phrase "not tax advice," negating it.

- [ ] **Step 5: Write the page and wire the route**

Create `frontend/src/pages/ReportsPage.tsx`:

```tsx
import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { CashFlowCard, SpendingCard, TaxCard, YearInReviewCard } from "../ReportsCards";
import { ChecklistCard, DocumentList, UploadForm } from "../VaultPanel";
import { PageHead } from "../ui/Shell";

function SubTabs() {
  const tabs = [
    { to: "/reports", label: "Spending", end: true },
    { to: "/reports/cash-flow", label: "Cash flow", end: false },
    { to: "/reports/year", label: "Year in review", end: false },
    { to: "/reports/tax", label: "Tax", end: false },
    { to: "/reports/vault", label: "Vault", end: false },
  ];
  return (
    <nav className="rise mb-6 flex gap-1 overflow-x-auto" style={{ scrollbarWidth: "none" } as React.CSSProperties}>
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            [
              "shrink-0 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors",
              isActive ? "bg-[rgba(198,242,78,0.08)] text-bone" : "text-muted hover:bg-[rgba(237,234,228,0.04)] hover:text-bone",
            ].join(" ")
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

function SpendingTab() {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const end = new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().slice(0, 10);
  const [groupBy, setGroupBy] = useState<"category" | "merchant" | "month">("category");

  return (
    <>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <span className="label">Group by</span>
        <select
          aria-label="Group spending by"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as "category" | "merchant" | "month")}
        >
          <option value="category">Category</option>
          <option value="merchant">Merchant</option>
          <option value="month">Month</option>
        </select>
      </label>
      <SpendingCard start={start} end={end} groupBy={groupBy} />
    </>
  );
}

export function ReportsPage() {
  const year = new Date().getFullYear();
  return (
    <>
      <PageHead title="Reports" sub="Spending, cash flow, taxes, and the document vault." />
      <SubTabs />
      <Routes>
        <Route index element={<SpendingTab />} />
        <Route path="cash-flow" element={<CashFlowCard />} />
        <Route path="year" element={<YearInReviewCard year={year} />} />
        <Route path="tax" element={<TaxCard year={year} />} />
        <Route
          path="vault"
          element={
            <>
              <UploadForm />
              <ChecklistCard />
              <DocumentList />
            </>
          }
        />
      </Routes>
    </>
  );
}
```

`ReportsPage.tsx` imports `ChecklistCard`, `DocumentList`, `UploadForm` from `../VaultPanel` — that file does not exist yet (Task 11 creates it). This is deliberate: Task 10's own frontend gate (`npm run build`) will fail until Task 11 lands, exactly the way P1's Task 10 mounted components Task 11 hadn't written yet. **Do not run the frontend gate at the end of this task** — Step 6 below runs only the vitest suite for the files this task actually finished; the full `npm run build` gate runs at the end of Task 11, once `VaultPanel.tsx` exists.

In `frontend/src/App.tsx`, add the import:

```tsx
import { ReportsPage } from "./pages/ReportsPage";
```

and a new route, alongside the existing `/investments/*` one (also a wildcard, for the same reason — `ReportsPage` owns its own sub-routes):

```tsx
          <Route
            path="/reports/*"
            element={
              <Protected>
                <ReportsPage />
              </Protected>
            }
          />
```

- [ ] **Step 6: Run the vitest suite for the files this task finished**

Run: `cd frontend && npm test -- ReportsCards`
Expected: PASS — 4 tests. (`npm test` alone will also pick up `App.tsx`'s import of the not-yet-created `VaultPanel.tsx` failing at the *build* step, not the test step — vitest transpiles per-file and does not fail on an unrelated file's unresolved import until something actually renders through that path, but do not treat a clean `npm test` here as the phase gate; `npm run build` is deferred to Task 11 as noted above.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/reports.ts frontend/src/tax.ts frontend/src/ReportsCards.tsx \
        frontend/src/ReportsCards.test.tsx frontend/src/pages/ReportsPage.tsx frontend/src/App.tsx
git commit -m "feat: spending, cash flow, year-in-review, and tax reporting cards"
```

---

### Task 11: Frontend — the vault panel and the beneficiary field

**Files:**
- Create: `frontend/src/vault.ts`
- Create: `frontend/src/VaultPanel.tsx`
- Create: `frontend/src/VaultPanel.test.tsx`
- Modify: `frontend/src/data.ts`
- Modify: `frontend/src/pages/AccountDetailPage.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `API_BASE` (`./api/client`); `usd` (`./money`); `Card`, `Empty` (`./ui/Shell`).
- Produces: `useDocuments`, `useChecklist`, `useUploadDocument`, `useDeleteDocument`, `documentDownloadUrl` (`vault.ts`); `UploadForm`, `DocumentList`, `ChecklistCard` (`VaultPanel.tsx`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/VaultPanel.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ChecklistCard, DocumentList, UploadForm } from "./VaultPanel";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const originalFetch = globalThis.fetch;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  globalThis.fetch = originalFetch;
});

describe("DocumentList", () => {
  it("lists uploaded documents by title and kind", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      {
        id: "d1", kind: "will", title: "My Will", filename: "will.pdf",
        content_type: "application/pdf", size_bytes: 1024, notes: null, created_at: "2026-07-01T00:00:00Z",
      },
    ]);
    render(<DocumentList />, { wrapper });
    await screen.findByText("My Will");
    expect(screen.getByText(/will/i)).toBeInTheDocument();
  });

  it("shows an empty state with nothing uploaded", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<DocumentList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/no documents/i)).toBeInTheDocument());
  });
});

describe("ChecklistCard", () => {
  it("shows every checklist item and its gap detail", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [
        { label: "Will on file", satisfied: false, detail: "No will uploaded to the vault yet." },
        { label: "Beneficiary on every retirement/insurance account", satisfied: true, detail: "All set." },
      ],
      gaps: 1,
    });
    render(<ChecklistCard />, { wrapper });
    await screen.findByText("Will on file");
    expect(screen.getByText("No will uploaded to the vault yet.")).toBeInTheDocument();
  });
});

describe("UploadForm", () => {
  it("submits kind, title, and the file as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "d1" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<UploadForm />, { wrapper });

    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "My Will" } });
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "will" } });
    const file = new File(["will contents"], "will.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Upload document"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- VaultPanel`
Expected: FAIL — cannot resolve `./VaultPanel`.

- [ ] **Step 3: Write the hooks**

Create `frontend/src/vault.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, API_BASE } from "./api/client";

export type DocumentKind = "will" | "trust" | "insurance" | "deed" | "title" | "statement" | "other";

export type VaultDocument = {
  id: string;
  kind: DocumentKind;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  notes: string | null;
  created_at: string;
};

export type ChecklistItem = { label: string; satisfied: boolean; detail: string };
export type Checklist = { items: ChecklistItem[]; gaps: number };

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: () => apiFetch<VaultDocument[]>("/documents") });
}

export function useChecklist() {
  return useQuery({
    queryKey: ["estate-checklist"],
    queryFn: () => apiFetch<Checklist>("/estate/checklist"),
  });
}

export function documentDownloadUrl(id: string) {
  return `${API_BASE}/documents/${id}/download`;
}

type UploadInput = { file: File; kind: DocumentKind; title: string; notes: string };

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, kind, title, notes }: UploadInput) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      form.append("title", title);
      if (notes) form.append("notes", notes);
      // Not apiFetch: it always sets Content-Type: application/json, which would
      // stomp the multipart boundary the browser sets for FormData automatically.
      const res = await fetch(`${API_BASE}/documents`, { method: "POST", credentials: "include", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? res.statusText);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["estate-checklist"] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["estate-checklist"] });
    },
  });
}
```

- [ ] **Step 4: Write the panel**

Create `frontend/src/VaultPanel.tsx`:

```tsx
import { useState } from "react";
import type { DocumentKind } from "./vault";
import { documentDownloadUrl, useChecklist, useDeleteDocument, useDocuments, useUploadDocument } from "./vault";
import { Card, Empty } from "./ui/Shell";

const KINDS: DocumentKind[] = ["will", "trust", "insurance", "deed", "title", "statement", "other"];

export function UploadForm() {
  const upload = useUploadDocument();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<DocumentKind>("will");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Upload a document</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return;
          upload.mutate(
            { file, kind, title, notes },
            { onSuccess: () => { setFile(null); setTitle(""); setNotes(""); } },
          );
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="flex flex-col gap-1.5">
          <span className="label">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Document type</span>
          <select aria-label="Document type" value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">File</span>
          <input
            type="file"
            aria-label="Upload document"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        </label>
        <button className="btn" disabled={upload.isPending || !file}>
          {upload.isPending ? "Uploading…" : "Upload"}
        </button>
        {upload.isError && <span className="text-sm text-clay">{(upload.error as Error).message}</span>}
      </form>
      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        Files are encrypted before they're written to disk. Only decrypted, in memory,
        for the moment you download them.
      </p>
    </Card>
  );
}

export function DocumentList() {
  const { data = [], isLoading } = useDocuments();
  const remove = useDeleteDocument();

  if (isLoading) return <Empty>Loading…</Empty>;
  if (data.length === 0) return <Empty>No documents yet — upload your first one above.</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">Documents</h2>
      <ul className="divide-y divide-line">
        {data.map((d) => (
          <li key={d.id} className="flex items-center gap-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{d.title}</span>
              <span className="label">{d.kind} · {d.filename}</span>
            </span>
            <a href={documentDownloadUrl(d.id)} className="text-[13px] text-acid">
              Download
            </a>
            <button
              onClick={() => remove.mutate(d.id)}
              aria-label={`Delete ${d.title}`}
              className="text-[13px] text-muted transition-colors hover:text-clay"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function ChecklistCard() {
  const { data, isLoading } = useChecklist();
  if (isLoading || !data) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Estate readiness</h2>
        <span className="label">{data.gaps === 0 ? "All set" : `${data.gaps} gap${data.gaps === 1 ? "" : "s"}`}</span>
      </div>
      <ul className="flex flex-col gap-3">
        {data.items.map((item) => (
          <li key={item.label} className="flex items-start gap-3 text-[13px]">
            <span aria-hidden className={item.satisfied ? "text-acid" : "text-clay"}>
              {item.satisfied ? "✓" : "✕"}
            </span>
            <span>
              <span className="block text-bone">{item.label}</span>
              <span className="text-muted">{item.detail}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        This list reports gaps — it doesn't draft a will, a beneficiary form, or a deed.
        Upload the real documents above once you have them.
      </p>
    </Card>
  );
}
```

- [ ] **Step 5: Add the beneficiary field to the accounts type and edit form**

In `frontend/src/data.ts`, add one field to `Account`:

```ts
export type Account = {
  id: string;
  name: string;
  type: string;
  institution: string | null;
  balance: string;
  currency: string;
  beneficiary: string | null;
};
```

In `frontend/src/pages/AccountDetailPage.tsx`, add a field to the edit form. In the `<form onSubmit>` handler, add `beneficiary` to the `save.mutate({...})` call:

```tsx
              save.mutate({
                name: String(form.get("name")),
                type: String(form.get("type")),
                institution: String(form.get("institution")),
                beneficiary: String(form.get("beneficiary")),
              });
```

and add the input, after the Institution field:

```tsx
            <label className="flex flex-col gap-1.5">
              <span className="label">Beneficiary</span>
              <input name="beneficiary" defaultValue={account.beneficiary ?? ""} placeholder="Optional" />
            </label>
```

- [ ] **Step 6: Run the frontend test suite**

Run: `cd frontend && npm test`
Expected: PASS. `ReportsPage.tsx`'s import of `../VaultPanel` now resolves.

- [ ] **Step 7: Build and lint**

```bash
cd frontend && npm run build && npm run lint
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/vault.ts frontend/src/VaultPanel.tsx frontend/src/VaultPanel.test.tsx \
        frontend/src/data.ts frontend/src/pages/AccountDetailPage.tsx
git commit -m "feat: an encrypted document vault panel, and a beneficiary field on accounts"
```

---

### Task 12: Navigation — one `MORE` entry, STOP-gated

**Re-run the STOP-section verification at the top of this plan before starting this task.** Run `grep -n "MORE" frontend/src/ui/Shell.tsx` (or open the file and look), and check `cd backend && .venv/Scripts/python -m alembic heads` for whether P2's migration has landed on top of P5's.

**Files:**
- Modify: `frontend/src/ui/Shell.tsx`
- Modify: `frontend/src/pages/OverviewPage.tsx` (Branch B only)

**Branch A — a `MORE` array exists (P2's own MoreMenu plan has merged by execution time).** Add exactly one entry, after whatever P2 (and possibly P3) already put there, and touch nothing else in the file:

```tsx
  { to: "/reports", label: "Reports", short: "Reports", end: false, glyph: "▦" },
```

Do not rename `NAV`, do not touch `MoreMenu.tsx`, do not add a sixth entry to the phone tab bar's fixed slots. This is the entire task in this branch.

- [ ] Run: `cd frontend && npm test && npm run build && npm run lint`
- [ ] Commit: `git add frontend/src/ui/Shell.tsx && git commit -m "feat: Reports joins the More menu"`

**Branch B — no `MORE` array exists (the state verified at the top of this plan, current as of 2026-08-02).** P2's own MoreMenu plan hasn't landed, so there is nothing to add one entry to. The five-tab phone ceiling PLAN-CONSTRAINTS.md documents still applies, and adding a sixth item to `NAV` violates it. This is the identical problem P3's own plan hit for Goals, and this task copies its resolution rather than inventing a second one:

1. Do not touch `NAV` in `frontend/src/ui/Shell.tsx` — it drives both the desktop sidebar and the mobile tab bar from the same array, and there is no separate desktop-only list to extend without either P2's MoreMenu split or a second array this plan would have to invent (P2's job, not P5's).
2. Instead, link to Reports from the Overview page. In `frontend/src/pages/OverviewPage.tsx`, add a small link near the bottom of the page (wherever the existing content ends, following whatever pattern the file already uses for a closing link — e.g. next to a forecast or assistant card if P3/P4 have already added one, otherwise standalone):

```tsx
      <p className="mt-2 text-right text-[11px]">
        <Link to="/reports" className="label transition-colors hover:text-bone">
          View reports →
        </Link>
      </p>
```

Add `import { Link } from "react-router-dom";` to the top of `OverviewPage.tsx` if it isn't already imported.

3. Leave a comment at the top of `frontend/src/ui/Shell.tsx` recording why, following the exact pattern P3 left for Goals:

```tsx
// ponytail: Reports has no NAV/MORE entry yet — P2's MoreMenu split (PLAN-CONSTRAINTS.md,
// "Navigation") hasn't landed as of P5. The route exists (/reports) and Overview links
// to it directly. When P2 ships MoreMenu.tsx and a MORE array, add one entry here for
// Reports and delete the Overview link — do not leave both.
```

If a prior phase (P3) already left an equivalent comment for Goals, append this Reports note to the same comment block rather than writing a second, separate one.

- [ ] Run: `cd frontend && npm test && npm run build && npm run lint`
- [ ] Commit: `git add frontend/src/ui/Shell.tsx frontend/src/pages/OverviewPage.tsx && git commit -m "feat: link to Reports from Overview until the More menu exists (Branch B)"`

Whichever branch applies, the commit message must say which branch was taken, so a later reader isn't left guessing.

---

### Task 13: End-to-end flow, README, CHANGELOG, and the full gate

**Files:**
- Create: `frontend/e2e/reports.spec.ts`
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Write the Playwright flow**

Read an existing spec in `frontend/e2e/` (e.g. `categorization.spec.ts`) and follow its setup. Create `frontend/e2e/reports.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("spending report, vault upload, and the estate checklist", async ({ page }) => {
  const stamp = Date.now();
  const title = `Will ${stamp}`;

  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();

  await page.goto("/reports/vault");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Document type").selectOption("will");
  await page.getByLabel("Upload document").setInputFiles({
    name: "will.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("the whole will, for the e2e run"),
  });
  await page.getByRole("button", { name: /upload/i }).click();
  await expect(page.getByText(title)).toBeVisible();

  // The checklist should now report the will as on file.
  await expect(page.getByText(/will on file/i)).toBeVisible();

  // Clean up — this runs against the real local database.
  await page.getByRole("button", { name: `Delete ${title}` }).click();
  await expect(page.getByText(title)).toHaveCount(0);
});
```

- [ ] **Step 2: Run the e2e suite**

Run: `docker compose up -d` then `cd frontend && npm run dev` in one terminal and `npm run e2e` in another.
Expected: PASS.

- [ ] **Step 3: Update the README**

In `README.md`, under "## What's here", add:

```markdown
- **Reports** — spending by category, merchant, or month; income vs. expense over the
  trailing year; a year-in-review summary (savings rate, biggest category, biggest
  single transaction, subscriptions started and cancelled, net worth change).
- **Tax reporting** — FIFO realized gains from the trade log, a dividend/interest
  summary from categorized transactions, and a Schedule-D-shaped CSV export. Reporting
  only: no filing, no advice, and wash-sale detection is explicitly not implemented —
  the export says so on its own page.
- **Document vault** — upload a will, a deed, an insurance policy; files are encrypted
  with the same AES-GCM envelope that already protects bank credentials, and only ever
  decrypted, in memory, for the moment you download them. A computed estate-readiness
  checklist reports gaps (a will on file? a beneficiary on every retirement account? a
  deed for every property?) — it never drafts a document.
- **Export everything** — `GET /export/all.zip` is every table the household owns, one
  CSV per table, straight from the schema.
```

In the "Not here yet" list, remove `Budgets, reports.` if P2 has merged by the time this runs (leave `Budgets` if it hasn't) — reports are done as of this phase either way. Replace the line with whichever is accurate:

```markdown
- See the roadmap in `docs/superpowers/specs/2026-07-30-origin-parity-design.md` for
  anything still listed there.
```

- [ ] **Step 4: Update the changelog**

Add a new section to `CHANGELOG.md`, above the P1 entry (or above whichever phase entries already exist, matching the format those already established):

```markdown
## P5 (reports, tax, and the document vault)

### Added
- `services/reports.py`: spending grouped by category, merchant, or month; income vs.
  expense over a trailing window; a year-in-review summary reusing
  `services/snapshots.py` for its net worth delta.
- `services/tax.py`: a from-scratch FIFO lot-matching replay over the trade log,
  separate from `services/portfolio.py`'s average-cost engine; a dividend/interest
  summary from categorized transactions; a Schedule-D-shaped CSV export that discloses
  wash sales are not handled.
- `documents` table and `services/documents.py`: an encrypted vault reusing the
  AES-GCM envelope already sealing provider credentials. Files are decrypted only in
  memory, only for a download.
- `accounts.beneficiary`, a nullable column.
- `services/estate.py`: a computed estate-readiness checklist — will on file,
  beneficiary on every retirement account, a deed for every property account. No
  storage of its own, and no document generation.
- `GET /export/all.zip`: every table the household owns, one CSV per table, enumerated
  from the model registry so a new table is a test failure until it's routed.
- Frontend: a Reports page with spending, cash-flow, year-in-review, tax, and vault
  tabs.
```

- [ ] **Step 5: Full gate**

```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
cd ../frontend && npm test && npm run build && npm run lint
```

Every one must pass. Do not claim P5 complete on a partial run — paste the actual output.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/reports.spec.ts README.md CHANGELOG.md
git commit -m "docs: P5 ships — reports, tax reporting, and the document vault"
```

---

## Self-Review

**Spec coverage** — every P5 requirement from `2026-07-30-origin-parity-design.md` §5:

| Spec requirement | Task |
|---|---|
| `GET /reports/spending?start&end&group_by=` | 1 |
| `GET /reports/income-vs-expense?months=` | 2 |
| `GET /reports/year-in-review?year=` — total in/out, savings rate, biggest category, biggest transaction, new/cancelled subscriptions, net worth delta | 2 |
| `GET /tax/realized-gains?year=` — FIFO over `models/trade.py` | 3 |
| `GET /tax/income-summary?year=` — dividends + interest from categorized transactions | 4 |
| `GET /tax/export?year=` — Schedule-D-shaped CSV | 4 |
| Wash-sale detection cut, disclosed on the export's face | 4 |
| `documents` table with all listed columns (adjusted per deviation 1) | 5 |
| Files encrypted at rest, decrypted only in the response stream | 6, 7 |
| `accounts.beneficiary`, nullable text, not a new model | 5 |
| Estate readiness checklist — computed, no storage, reports gaps | 8 |
| `GET /export/all.zip` — every table, one CSV each | 9 |
| FIFO across partial sells and multiple lots (test) | 3 |
| Realized gains for a year with no sells (test) | 3 |
| Upload/download round-trip byte-identical (test) | 6, 7 |
| Ciphertext on disk is not the plaintext (test) | 6 |
| A document from another household is not reachable (test) | 6, 7 |
| Checklist gap detection (test) | 8 |
| Export containing every table, asserted against the model registry (test) | 9 |
| One Alembic revision for the whole phase | 5 |
| PDF rendering, document generation, OCR, wash sales, non-FIFO cost basis, e-signature all cut | throughout — none of the thirteen tasks build any of them |
| Nav: exactly one `MORE` entry, no menu rebuild | 12 |

**Deviations from the spec, recorded up front and restated here:** the eight numbered items after Global Constraints — no separate `nonce`/`wrapped_key` columns (1), no `documents.updated_at` (2), income summary sources both dividends and interest from transactions only (3), realized gains cover tax-advantaged accounts because the schema can't distinguish them (4), the checklist's "retirement/insurance" and "property" account mappings (5), the checklist's deed check comparing counts rather than per-account links (6), "cancelled" subscriptions approximated from `last_charged_on` (7), and the export's hardcoded exclusion of `users`/`provider_connections` (8). Each is a schema or data-availability limitation the spec's prose didn't anticipate, not a shortcut taken for convenience.

**One additional deviation not listed above, found while writing the tasks:** the spec's P5 section doesn't give the estate checklist or the vault upload/download endpoints explicit route paths — only the `documents` schema and a narrative description of the checklist. This plan chose `GET/POST /documents`, `GET /documents/{id}/download`, `DELETE /documents/{id}`, and `GET /estate/checklist` as the smallest, most conventional shape consistent with every other resource in this API (compare `GET/POST /accounts`, `PATCH/DELETE /accounts/{id}`). No other route shape was considered defensible enough to record as a real alternative.

**Type consistency** — `SpendingBucket.key_id: uuid.UUID | None` (Task 1) is threaded unchanged through `SpendingBucketOut` (Task 1), `year_in_review`'s reuse of `spending()` (Task 2), and the frontend's `SpendingBucket.key_id: string | null` (Task 10) — Pydantic serializes the UUID to a string on the wire, matching the TypeScript type. `RealizedGain`'s field names (`opened_on`, `closed_on`, `proceeds`, `cost_basis`, `gain`, `term`) are identical across the dataclass (Task 3), `RealizedGainOut` (Task 3), and `RealizedGain` on the frontend (Task 10) — no renaming at any hop. `DocumentKind` is defined once, in `app.models.document` (Task 5), and imported by `schemas/document.py` (Task 7) and `services/estate.py` (Task 8) rather than redefined; its frontend twin in `vault.ts` (Task 11) lists the same seven values in the same order. `documents.save`'s keyword-only signature (Task 6) is called identically by `api/documents.py::upload_document` (Task 7) with no positional-argument drift.

**Placeholder scan** — no `TODO`, no stub function body, and no test skipped; every service function shown is the final version, not a scratch draft. The one deliberately sequenced gap is Task 10's `ReportsPage.tsx`, which imports `../VaultPanel` before that file exists — Task 10's own steps say so explicitly and defer the frontend build gate to Task 11, the same sequencing P1 used when `TransactionsPage.tsx` mounted `RulesCard`/`UncategorizedCard` in a task before their own file landed.

**Nothing here re-litigates the Navigation decision.** Task 12 is the only task touching `Shell.tsx`, adds at most one entry to an existing `MORE` array, and its Branch B fallback is copied from P3's own plan rather than invented — the same STOP-gate shape PLAN-CONSTRAINTS.md and every other P2–P5 plan uses for a dependency that may or may not have landed by execution time.
