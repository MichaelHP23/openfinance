# P1 Categorization Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every transaction gets a category automatically, from a rule list the user can read, reorder, and delete.

**Architecture:** A seeded system taxonomy fills the `categories` table that has existed and gone unused since M0. A new `category_rules` table holds ordered match conditions; a pure matching function picks the first rule that fits and the service layer applies it at CSV import, at provider sync, and on demand over history. Merchant matching reuses `recurring.merchant_key()` — the normalization already shipped for subscription detection — so a rule written once matches the same way everywhere. One optional LLM endpoint proposes rules for unmatched merchants and writes nothing until the user confirms.

**Tech Stack:** FastAPI, SQLAlchemy 2 (`Mapped`/`mapped_column`), Alembic, Pydantic v2, pytest + testcontainers Postgres, React 19, TanStack Query, react-hook-form, Vitest, Playwright.

## Global Constraints

- Money is `Decimal` in Python and `NUMERIC(19,4)` in Postgres. Never `float`. Never round-trip a summed figure through `float`.
- Every financial row carries `household_id`. Every service function takes `household_id` and filters on it. Cross-household reads are a tenancy bug, and `backend/tests/test_tenancy.py` exists to catch them.
- **No new dependencies.** Everything here uses libraries already installed.
- Backend gates: `.venv/Scripts/python -m pytest`, `-m ruff check app tests`, `-m mypy app`. All three must pass before a commit.
- Frontend gates: `npm test`, `npm run typecheck`, `npm run lint`.
- Backend tests need Docker running — `conftest.py` spins up a real `postgres:17` container.
- Tests build the schema with `Base.metadata.create_all`, **not** with Alembic. Any seed data the app requires must therefore live in an importable function that both the migration and the tests can call. This is why Task 1 puts the taxonomy in `app/services/categories.py` and not inline in the migration.
- System categories are rows with `household_id IS NULL`. They are readable by every household and mutable by none.
- The LLM never calculates and never writes. It proposes; the user confirms; the app writes.
- Follow the existing file shapes: service modules are flat functions taking `(db, household_id, ...)`, routers are thin and translate service exceptions into `HTTPException`.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `backend/app/models/category_rule.py` | `CategoryRule` model + `MatchType` enum |
| `backend/app/schemas/category.py` | Pydantic in/out for categories, rules, suggestions |
| `backend/app/services/categories.py` | Taxonomy constant, `ensure_system_categories`, category CRUD |
| `backend/app/services/categorization.py` | Matching engine, rule CRUD, apply/backfill, uncategorized rollup |
| `backend/app/api/categories.py` | Both routers: `/categories` and `/category-rules` |
| `backend/migrations/versions/e1f3a2c4b508_category_rules.py` | `category_rules` table, txn index, taxonomy seed |
| `backend/tests/test_categorization.py` | Matching engine + apply/backfill service tests |
| `backend/tests/test_categories_api.py` | Category and rule endpoint tests |
| `frontend/src/categories.ts` | Types + TanStack hooks |
| `frontend/src/categories.tsx` | `CategoryPicker`, `RulesCard`, `UncategorizedCard` |
| `frontend/src/categories.test.tsx` | Component tests |

**Modify:**

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Register `CategoryRule` so `create_all` sees it |
| `backend/app/main.py` | Include the two new routers |
| `backend/app/services/csv_import.py` | Categorize what was just imported |
| `backend/app/services/sync.py` | Categorize what was just synced |
| `backend/app/providers/llm.py` | Add a JSON-returning call if one is not already exposed |
| `frontend/src/data.ts` | `Txn` gains `category_id` |
| `frontend/src/transactions.tsx` | Category cell + inline edit + "always" prompt |
| `frontend/src/pages/TransactionsPage.tsx` | Mount `RulesCard` and `UncategorizedCard` |
| `README.md`, `CHANGELOG.md` | Move categorization out of "Not here yet" |

No new nav tab. `Shell.tsx` documents five tabs as the ceiling for the mobile bar; rules live on the Transactions page.

---

### Task 1: Category taxonomy and the rule table

**Files:**
- Create: `backend/app/models/category_rule.py`
- Create: `backend/app/services/categories.py`
- Create: `backend/migrations/versions/e1f3a2c4b508_category_rules.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_categorization.py`

**Interfaces:**
- Consumes: `Category` from `app.models.category`, `Base`/`UUIDMixin`/`TimestampMixin` from `app.models.base`.
- Produces:
  - `MatchType` enum: `merchant_contains | merchant_exact | merchant_regex`
  - `CategoryRule` model with columns `id, household_id, match_type, pattern, min_amount, max_amount, account_id, category_id, priority, source, created_at, updated_at`
  - `RuleSource` enum: `user | suggested`
  - `TAXONOMY: dict[str, list[str]]` — group name → leaf names
  - `system_category_id(path: str) -> uuid.UUID` — deterministic id for `"Group"` or `"Group/Leaf"`
  - `ensure_system_categories(db: Session) -> int` — idempotent, returns rows inserted

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_categorization.py`:

```python
import uuid

from app.models.category import Category
from app.services.categories import (
    TAXONOMY,
    ensure_system_categories,
    system_category_id,
)


def test_seed_creates_groups_and_leaves(db):
    inserted = ensure_system_categories(db)
    expected = len(TAXONOMY) + sum(len(v) for v in TAXONOMY.values())
    assert inserted == expected

    groceries = db.get(Category, system_category_id("Food & Drink/Groceries"))
    assert groceries is not None
    assert groceries.name == "Groceries"
    assert groceries.household_id is None
    assert groceries.parent_id == system_category_id("Food & Drink")


def test_seed_is_idempotent(db):
    ensure_system_categories(db)
    assert ensure_system_categories(db) == 0


def test_system_category_ids_are_stable():
    assert system_category_id("Food & Drink/Groceries") == system_category_id(
        "Food & Drink/Groceries"
    )
    assert isinstance(system_category_id("Transfers"), uuid.UUID)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.categories'`

- [ ] **Step 3: Write the taxonomy and seeder**

Create `backend/app/services/categories.py`:

```python
"""The system category taxonomy, and CRUD over household-owned categories.

The taxonomy lives here rather than in the migration because tests build their schema
with `Base.metadata.create_all`, never with Alembic — so a seed that only exists inside
a migration would be absent in every test. The migration imports this module.

System category ids are uuid5 over the category's path, so they are identical on every
install. That makes the seeder idempotent without a unique constraint, and it means a
rule exported from one install still points at a real category on another.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate

# uuid5 needs a fixed namespace. Any constant UUID does; this one was generated once.
_NAMESPACE = uuid.UUID("6f2a1c14-9a5f-4b3e-8d21-0c7f5a9e4b10")

TAXONOMY: dict[str, list[str]] = {
    "Income": ["Paycheck", "Bonus", "Interest", "Dividends", "Refunds", "Other Income"],
    "Housing": [
        "Rent",
        "Mortgage",
        "Property Tax",
        "Home Insurance",
        "Home Maintenance",
        "Furnishings",
    ],
    "Bills & Utilities": [
        "Electric",
        "Gas",
        "Water",
        "Internet",
        "Mobile Phone",
        "Streaming",
        "Other Bills",
    ],
    "Transport": [
        "Gas & Fuel",
        "Public Transit",
        "Rideshare",
        "Parking",
        "Car Payment",
        "Car Insurance",
        "Car Maintenance",
    ],
    "Food & Drink": ["Groceries", "Restaurants", "Coffee", "Bars", "Delivery"],
    "Shopping": ["Clothing", "Electronics", "Household Goods", "Gifts", "Hobbies"],
    "Health": ["Doctor", "Pharmacy", "Dental", "Vision", "Health Insurance", "Fitness"],
    "Entertainment": ["Movies & Music", "Games", "Events", "Books"],
    "Travel": ["Flights", "Hotels", "Rental Car", "Vacation Other"],
    "Personal": ["Haircut & Beauty", "Childcare", "Education", "Pets", "Subscriptions"],
    "Financial": ["Bank Fees", "Interest Charged", "Taxes", "Investments", "Charity"],
    "Transfers": ["Transfer", "Credit Card Payment", "Loan Payment"],
}


def system_category_id(path: str) -> uuid.UUID:
    """Stable id for a system category. `path` is "Group" or "Group/Leaf"."""
    return uuid.uuid5(_NAMESPACE, f"openfinance:category:{path}")


def ensure_system_categories(db: Session) -> int:
    """Insert any missing system category. Returns how many rows it added."""
    present = set(
        db.scalars(select(Category.id).where(Category.household_id.is_(None)))
    )
    added = 0
    for group, leaves in TAXONOMY.items():
        group_id = system_category_id(group)
        if group_id not in present:
            db.add(Category(id=group_id, household_id=None, name=group, parent_id=None))
            added += 1
        for leaf in leaves:
            leaf_id = system_category_id(f"{group}/{leaf}")
            if leaf_id not in present:
                db.add(
                    Category(
                        id=leaf_id, household_id=None, name=leaf, parent_id=group_id
                    )
                )
                added += 1
    db.commit()
    return added
```

Create `backend/app/models/category_rule.py`:

```python
import enum
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class MatchType(str, enum.Enum):
    merchant_contains = "merchant_contains"
    merchant_exact = "merchant_exact"
    merchant_regex = "merchant_regex"


class RuleSource(str, enum.Enum):
    user = "user"           # written by hand, or confirmed from a transaction edit
    suggested = "suggested"  # confirmed from an LLM proposal


class CategoryRule(Base, UUIDMixin, TimestampMixin):
    """One condition set that assigns a category.

    A rule matches when every non-null condition holds. Rules are tried in `priority`
    order, lowest first, and the first match wins — so ordering is the whole conflict
    model. No precedence lattice, no scoring.
    """

    __tablename__ = "category_rules"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    match_type: Mapped[MatchType] = mapped_column(
        __import__("sqlalchemy").Enum(MatchType, name="rule_match_type")
    )
    pattern: Mapped[str] = mapped_column(String(200))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE")
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    source: Mapped[RuleSource] = mapped_column(
        __import__("sqlalchemy").Enum(RuleSource, name="rule_source"),
        default=RuleSource.user,
    )
```

Replace the two `__import__("sqlalchemy").Enum` calls with a normal `from sqlalchemy import Enum` at the top and plain `Enum(...)` — the inline form above is only there to keep the import list visible. Final import line:

```python
from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
```

Add to `backend/app/models/__init__.py`, alongside the existing model imports:

```python
from app.models.category_rule import CategoryRule, MatchType, RuleSource  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Write the migration**

Create `backend/migrations/versions/e1f3a2c4b508_category_rules.py`. Set `down_revision` to the current head — find it with `cd backend && .venv/Scripts/python -m alembic heads`. At time of writing that is `d5f2c1a83b70`; use whatever the command reports.

```python
"""category rules, transaction category index, system taxonomy seed

Revision ID: e1f3a2c4b508
Revises: d5f2c1a83b70
Create Date: 2026-07-30

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.services.categories import ensure_system_categories

revision: str = "e1f3a2c4b508"
down_revision: Union[str, Sequence[str], None] = "d5f2c1a83b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the explicit .create() calls below own these types, matching the
# pattern established in a1b2c3d4e5f6.
rule_match_type = postgresql.ENUM(
    "merchant_contains",
    "merchant_exact",
    "merchant_regex",
    name="rule_match_type",
    create_type=False,
)
rule_source = postgresql.ENUM("user", "suggested", name="rule_source", create_type=False)


def upgrade() -> None:
    rule_match_type.create(op.get_bind(), checkfirst=True)
    rule_source.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "category_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_type", rule_match_type, nullable=False),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("min_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("max_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("source", rule_source, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_category_rules_household_id"), "category_rules", ["household_id"]
    )
    # spend_by_category over a decade of history is the only query here with real
    # growth; this is the index it wants.
    op.create_index(
        "ix_transactions_household_category_posted",
        "transactions",
        ["household_id", "category_id", "posted_at"],
    )
    ensure_system_categories(Session(bind=op.get_bind()))


def downgrade() -> None:
    op.drop_index("ix_transactions_household_category_posted", table_name="transactions")
    op.drop_table("category_rules")
    # Postgres does not drop an enum with its table — same fix as a1b2c3d4e5f6.
    rule_match_type.drop(op.get_bind(), checkfirst=True)
    rule_source.drop(op.get_bind(), checkfirst=True)
    # The seeded categories are deliberately left in place: transactions may reference
    # them, and a downgrade that orphans FKs is worse than a downgrade that leaves rows.
```

Note the `TimestampMixin` may also define `updated_at`. Open `backend/app/models/base.py` and mirror whatever columns it declares into the `create_table` call — the recurring migration is the reference for what the mixins expand to.

- [ ] **Step 6: Verify the migration applies and round-trips**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_migrations.py -v`
Expected: PASS. If that test only checks for a single head, also run the stack: `docker compose up -d postgres` then `.venv/Scripts/python -m alembic upgrade head` followed by `.venv/Scripts/python -m alembic downgrade -1` and `upgrade head` again. Both directions must succeed.

- [ ] **Step 7: Lint and type-check**

Run: `cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/category_rule.py backend/app/models/__init__.py \
        backend/app/services/categories.py backend/migrations/versions/e1f3a2c4b508_category_rules.py \
        backend/tests/test_categorization.py
git commit -m "feat: fill the categories table M0 built and never used"
```

---

### Task 2: The matching engine

**Files:**
- Create: `backend/app/services/categorization.py`
- Test: `backend/tests/test_categorization.py` (append)

**Interfaces:**
- Consumes: `CategoryRule`, `MatchType` (Task 1); `merchant_key` from `app.services.recurring`; `Transaction` from `app.models.transaction`.
- Produces:
  - `PATTERN_MAX = 200`
  - `class BadPattern(Exception)`
  - `compile_pattern(match_type: MatchType, pattern: str) -> None` — raises `BadPattern`; used by the API to validate before insert
  - `rule_matches(rule: CategoryRule, txn: Transaction) -> bool`
  - `pick_category(rules: list[CategoryRule], txn: Transaction) -> uuid.UUID | None` — first match by list order

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_categorization.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from app.models.category_rule import CategoryRule, MatchType
from app.models.transaction import Transaction
from app.services.categorization import (
    BadPattern,
    compile_pattern,
    pick_category,
    rule_matches,
)

GROCERIES = system_category_id("Food & Drink/Groceries")
COFFEE = system_category_id("Food & Drink/Coffee")


def _txn(merchant: str, amount: str = "-42.00", account_id=None) -> Transaction:
    return Transaction(
        household_id=uuid.uuid4(),
        account_id=account_id or uuid.uuid4(),
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
    )


def _rule(**kw) -> CategoryRule:
    base = dict(
        household_id=uuid.uuid4(),
        match_type=MatchType.merchant_contains,
        pattern="whole foods",
        category_id=GROCERIES,
        priority=100,
    )
    base.update(kw)
    return CategoryRule(**base)


def test_contains_matches_through_normalization():
    # merchant_key strips the "TST* " prefix, the store number, and the case.
    assert rule_matches(_rule(), _txn("TST* WHOLE FOODS #4471"))


def test_contains_does_not_match_unrelated_merchant():
    assert not rule_matches(_rule(), _txn("SHELL OIL"))


def test_exact_requires_the_whole_normalized_name():
    r = _rule(match_type=MatchType.merchant_exact, pattern="whole foods")
    assert rule_matches(r, _txn("WHOLE FOODS #4471"))
    assert not rule_matches(r, _txn("WHOLE FOODS MARKET"))


def test_regex_matches_normalized_name():
    r = _rule(match_type=MatchType.merchant_regex, pattern=r"^(whole foods|trader joe)")
    assert rule_matches(r, _txn("TRADER JOE S #22"))


def test_amount_band_bounds_the_match():
    r = _rule(min_amount=Decimal("-100.00"), max_amount=Decimal("-50.00"))
    assert rule_matches(r, _txn("WHOLE FOODS", "-75.00"))
    assert not rule_matches(r, _txn("WHOLE FOODS", "-20.00"))
    assert not rule_matches(r, _txn("WHOLE FOODS", "-150.00"))


def test_account_condition_bounds_the_match():
    account = uuid.uuid4()
    r = _rule(account_id=account)
    assert rule_matches(r, _txn("WHOLE FOODS", account_id=account))
    assert not rule_matches(r, _txn("WHOLE FOODS", account_id=uuid.uuid4()))


def test_first_rule_in_order_wins():
    specific = _rule(pattern="whole foods", category_id=COFFEE, priority=10)
    general = _rule(pattern="whole", category_id=GROCERIES, priority=50)
    assert pick_category([specific, general], _txn("WHOLE FOODS")) == COFFEE
    assert pick_category([general, specific], _txn("WHOLE FOODS")) == GROCERIES


def test_no_rule_matches_returns_none():
    assert pick_category([_rule()], _txn("SHELL OIL")) is None


def test_bad_regex_is_rejected_not_raised_at_match_time():
    try:
        compile_pattern(MatchType.merchant_regex, "(unclosed")
    except BadPattern:
        pass
    else:
        raise AssertionError("expected BadPattern")


def test_overlong_pattern_is_rejected():
    try:
        compile_pattern(MatchType.merchant_contains, "x" * 201)
    except BadPattern:
        pass
    else:
        raise AssertionError("expected BadPattern")


def test_a_rule_with_a_broken_pattern_never_matches():
    # Belt and braces: validation happens at write time, but a row that predates a
    # validation change must not take down categorization for every other rule.
    r = _rule(match_type=MatchType.merchant_regex, pattern="(unclosed")
    assert not rule_matches(r, _txn("ANYTHING"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.categorization'`

- [ ] **Step 3: Write the matching engine**

Create `backend/app/services/categorization.py`:

```python
"""Rule-based transaction categorization.

Deterministic. No ML, no LLM in the matching path — the LLM only ever proposes rules
for a human to confirm (see `app/api/categories.py::suggest`).

Merchant matching runs against `recurring.merchant_key()`, the same normalization
subscription detection uses. That means "TST* WHOLE FOODS #4471" and "WHOLE FOODS
MARKET 22" reduce to comparable strings, and a rule the user writes once behaves the
same in both features. Patterns are normalized with the same function on the way in, so
the user can type "Whole Foods" and not think about it.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category_rule import CategoryRule, MatchType
from app.models.transaction import Transaction
from app.services.recurring import merchant_key

# Patterns run against merchant keys, which are short. Capping the pattern keeps a
# pathological regex from having anything to chew on; there is no untrusted author here
# anyway, since the only writer is the household itself.
PATTERN_MAX = 200


class BadPattern(Exception):
    """A rule pattern that cannot be stored: empty, too long, or an invalid regex."""


def compile_pattern(match_type: MatchType, pattern: str) -> None:
    """Validate a pattern at write time. Raises BadPattern; returns nothing."""
    if not pattern or not pattern.strip():
        raise BadPattern("Pattern is empty")
    if len(pattern) > PATTERN_MAX:
        raise BadPattern(f"Pattern is longer than {PATTERN_MAX} characters")
    if match_type is MatchType.merchant_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise BadPattern(f"Invalid regular expression: {exc}") from exc


def _merchant_of(txn: Transaction) -> str:
    return merchant_key(txn.merchant_normalized or txn.merchant_raw)


def rule_matches(rule: CategoryRule, txn: Transaction) -> bool:
    """True when every non-null condition on the rule holds for the transaction."""
    if rule.account_id is not None and rule.account_id != txn.account_id:
        return False
    if rule.min_amount is not None and txn.amount < rule.min_amount:
        return False
    if rule.max_amount is not None and txn.amount > rule.max_amount:
        return False

    name = _merchant_of(txn)
    if rule.match_type is MatchType.merchant_regex:
        try:
            return re.search(rule.pattern, name) is not None
        except re.error:
            # A stored pattern that no longer compiles is dead, not fatal. Skipping it
            # keeps every other rule working.
            return False
    needle = merchant_key(rule.pattern)
    if rule.match_type is MatchType.merchant_exact:
        return name == needle
    return needle in name


def pick_category(rules: list[CategoryRule], txn: Transaction) -> uuid.UUID | None:
    """First matching rule wins. Caller supplies the rules already in priority order."""
    for rule in rules:
        if rule_matches(rule, txn):
            return rule.category_id
    return None


def rules_for(db: Session, household_id: uuid.UUID) -> list[CategoryRule]:
    """Every rule for the household, in the order they should be tried."""
    return list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.household_id == household_id)
            .order_by(CategoryRule.priority, CategoryRule.created_at)
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: PASS — 14 tests.

- [ ] **Step 5: Lint and type-check, then commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/categorization.py backend/tests/test_categorization.py
git commit -m "feat: match a transaction to a rule, reusing the subscription normalizer"
```

---

### Task 3: Apply, backfill, and the uncategorized rollup

**Files:**
- Modify: `backend/app/services/categorization.py`
- Test: `backend/tests/test_categorization.py` (append)

**Interfaces:**
- Consumes: `rules_for`, `pick_category` (Task 2).
- Produces:
  - `apply_to(db, household_id, txns: list[Transaction], rules=None) -> int` — sets `category_id` in place on rows that have none, returns how many changed. Does not commit.
  - `backfill(db, household_id, *, only_uncategorized: bool = True) -> int` — commits.
  - `UncategorizedMerchant` dataclass: `merchant: str`, `count: int`, `total: Decimal`
  - `uncategorized_merchants(db, household_id, limit: int = 100) -> list[UncategorizedMerchant]`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_categorization.py`. This test needs a real household and account, so follow whatever helper `backend/tests/test_transactions.py` already uses — read it first and reuse it rather than inventing a second fixture.

```python
from app.services import categorization


def test_apply_sets_category_on_uncategorized_rows(db, household, account):
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    txns = [
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
        ),
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 2, tzinfo=UTC),
            amount=Decimal("-9.00"),
            currency="USD",
            merchant_raw="SHELL OIL",
        ),
    ]
    db.add_all(txns)
    db.commit()

    assert categorization.apply_to(db, household.id, txns) == 1
    assert txns[0].category_id == GROCERIES
    assert txns[1].category_id is None


def test_backfill_leaves_hand_set_categories_alone(db, household, account):
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    hand_set = Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal("-42.00"),
        currency="USD",
        merchant_raw="WHOLE FOODS",
        category_id=COFFEE,
    )
    db.add(hand_set)
    db.commit()

    assert categorization.backfill(db, household.id) == 0
    db.refresh(hand_set)
    assert hand_set.category_id == COFFEE


def test_backfill_with_only_uncategorized_false_overwrites(db, household, account):
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    hand_set = Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal("-42.00"),
        currency="USD",
        merchant_raw="WHOLE FOODS",
        category_id=COFFEE,
    )
    db.add(hand_set)
    db.commit()

    assert categorization.backfill(db, household.id, only_uncategorized=False) == 1
    db.refresh(hand_set)
    assert hand_set.category_id == GROCERIES


def test_uncategorized_rollup_groups_by_normalized_merchant(db, household, account):
    db.add_all(
        [
            Transaction(
                household_id=household.id,
                account_id=account.id,
                posted_at=datetime(2026, 7, day, tzinfo=UTC),
                amount=Decimal("-10.00"),
                currency="USD",
                merchant_raw=raw,
            )
            for day, raw in [(1, "SHELL OIL #221"), (2, "SHELL OIL #907"), (3, "KROGER")]
        ]
    )
    db.commit()

    rollup = categorization.uncategorized_merchants(db, household.id)
    by_name = {r.merchant: r for r in rollup}
    assert by_name["shell oil"].count == 2
    assert by_name["shell oil"].total == Decimal("-20.00")
    assert by_name["kroger"].count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: FAIL — `AttributeError: module 'app.services.categorization' has no attribute 'apply_to'`

- [ ] **Step 3: Implement**

Append to `backend/app/services/categorization.py`:

```python
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal


def apply_to(
    db: Session,
    household_id: uuid.UUID,
    txns: list[Transaction],
    rules: list[CategoryRule] | None = None,
) -> int:
    """Categorize the given rows in place. Does not commit — the caller owns the txn.

    Only touches rows with no category. Overwriting is `backfill`'s job, and only when
    asked for explicitly.
    """
    if rules is None:
        rules = rules_for(db, household_id)
    if not rules:
        return 0
    changed = 0
    for txn in txns:
        if txn.category_id is not None:
            continue
        picked = pick_category(rules, txn)
        if picked is not None:
            txn.category_id = picked
            changed += 1
    return changed


def backfill(
    db: Session, household_id: uuid.UUID, *, only_uncategorized: bool = True
) -> int:
    """Re-run every rule over the household's history.

    `only_uncategorized` defaults true so a backfill can never silently undo a category
    the user set by hand. That default is the entire conflict model between hand edits
    and rules — there is no per-row "who set this" column, and adding one would only
    have to be kept in sync.
    """
    q = select(Transaction).where(Transaction.household_id == household_id)
    if only_uncategorized:
        q = q.where(Transaction.category_id.is_(None))
    txns = list(db.scalars(q))
    rules = rules_for(db, household_id)
    if not rules:
        return 0
    changed = 0
    for txn in txns:
        picked = pick_category(rules, txn)
        if picked is not None and picked != txn.category_id:
            txn.category_id = picked
            changed += 1
    db.commit()
    return changed


@dataclass
class UncategorizedMerchant:
    merchant: str
    count: int
    total: Decimal


def uncategorized_merchants(
    db: Session, household_id: uuid.UUID, limit: int = 100
) -> list[UncategorizedMerchant]:
    """Uncategorized spend rolled up by normalized merchant, biggest count first.

    Grouped in Python rather than SQL because the grouping key is `merchant_key`, which
    is Python. At one household's volume that is a few thousand rows and cheaper than
    maintaining a normalized column just to be able to GROUP BY it.
    """
    rows = db.scalars(
        select(Transaction).where(
            Transaction.household_id == household_id,
            Transaction.category_id.is_(None),
        )
    )
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for txn in rows:
        key = _merchant_of(txn)
        if not key:
            continue
        counts[key] += 1
        totals[key] += txn.amount
    out = [
        UncategorizedMerchant(merchant=k, count=counts[k], total=totals[k])
        for k in counts
    ]
    out.sort(key=lambda m: (-m.count, m.merchant))
    return out[:limit]
```

Move the new `from collections import defaultdict`, `from dataclasses import dataclass`, and `from decimal import Decimal` up into the module's import block rather than leaving them mid-file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categorization.py -v`
Expected: PASS — 18 tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/categorization.py backend/tests/test_categorization.py
git commit -m "feat: backfill categories without clobbering what you set by hand"
```

---

### Task 4: Categorize at import and at sync

**Files:**
- Modify: `backend/app/services/csv_import.py`
- Modify: `backend/app/services/sync.py`
- Test: `backend/tests/test_csv_import.py`, `backend/tests/test_sync.py` (append to each)

**Interfaces:**
- Consumes: `categorization.apply_to` (Task 3).
- Produces: no new signatures. `ImportResult` and `SyncResult` each gain a `categorized: int` field, defaulting to 0.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_csv_import.py` — reuse the fixtures already in that file:

```python
def test_import_categorizes_new_rows(db, household, account):
    from app.models.category_rule import CategoryRule, MatchType
    from app.services.categories import ensure_system_categories, system_category_id
    from app.services.csv_import import import_csv

    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=groceries,
            priority=100,
        )
    )
    db.commit()

    raw = "date,amount,merchant\n2026-07-01,-42.00,WHOLE FOODS #4471\n"
    result = import_csv(db, household.id, account.id, raw)

    assert result.imported == 1
    assert result.categorized == 1
    from sqlalchemy import select

    from app.models.transaction import Transaction

    txn = db.scalar(select(Transaction).where(Transaction.household_id == household.id))
    assert txn.category_id == groceries
```

Append the equivalent to `backend/tests/test_sync.py`, using the fake provider that file already defines:

```python
def test_sync_categorizes_new_transactions(db, household):
    """A synced transaction lands categorized, same as an imported one."""
    # Build the connection + fake provider exactly as the other tests in this file do,
    # add a CategoryRule matching the fake provider's merchant, run sync_connection,
    # then assert the resulting Transaction has that rule's category_id and that
    # result.categorized == 1.
```

Replace that docstring-only body with the real construction from the neighbouring tests before running — the fake provider's merchant strings are defined there and must be matched exactly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_csv_import.py tests/test_sync.py -v`
Expected: FAIL — `AttributeError: 'ImportResult' object has no attribute 'categorized'`

- [ ] **Step 3: Wire the hook into `csv_import.py`**

Change the dataclass and the tail of `import_csv`:

```python
@dataclass
class ImportResult:
    imported: int
    skipped: int
    categorized: int = 0
```

Replace the final `db.commit()` / `return` with:

```python
    db.flush()
    # Categorize before the commit so an import is one transaction: either the rows and
    # their categories land together, or neither does.
    fresh = [t for t in db.new if isinstance(t, Transaction)] if db.new else []
    categorized = categorization.apply_to(db, household_id, fresh)
    db.commit()
    return ImportResult(imported=imported, skipped=skipped, categorized=categorized)
```

`db.new` is empty after `flush()`, so collect the rows as they are created instead. Add a local list at the top of the loop body and append to it:

```python
    imported = skipped = 0
    added: list[Transaction] = []
```

then inside the loop, replace the bare `db.add(Transaction(...))` with:

```python
        txn = Transaction(
            household_id=household_id,
            account_id=account_id,
            posted_at=datetime.fromisoformat(row["date"]).replace(tzinfo=UTC),
            amount=Decimal(row["amount"]),
            currency="USD",
            merchant_raw=row["merchant"],
            external_id=ext,
        )
        db.add(txn)
        added.append(txn)
```

and the tail becomes:

```python
    categorized = categorization.apply_to(db, household_id, added)
    db.commit()
    return ImportResult(imported=imported, skipped=skipped, categorized=categorized)
```

Add the import at the top: `from app.services import accounts, categorization`.

- [ ] **Step 4: Wire the hook into `sync.py`**

Add `categorized: int = 0` to `SyncResult`. Collect created transactions in a list exactly as above — the loop already builds `Transaction(...)` inline; bind it to a name, `db.add` it, and append. Immediately before the existing `db.commit()` at the end of `sync_connection`:

```python
    result.categorized = categorization.apply_to(db, household_id, added)
    conn.last_synced_at = datetime.now(UTC)
    conn.status = ConnStatus.active
    db.commit()
```

Add `from app.services import categorization` to the imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_csv_import.py tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest`
Expected: all pass. `apply_to` returning 0 when there are no rules means every existing test is unaffected.

- [ ] **Step 7: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/csv_import.py backend/app/services/sync.py \
        backend/tests/test_csv_import.py backend/tests/test_sync.py
git commit -m "feat: categorize on the way in, so nothing arrives unsorted"
```

---

### Task 5: Category and rule schemas

**Files:**
- Create: `backend/app/schemas/category.py`

**Interfaces:**
- Produces: `CategoryCreate`, `CategoryUpdate`, `CategoryOut`, `RuleCreate`, `RuleUpdate`, `RuleOut`, `ReorderIn`, `BackfillIn`, `UncategorizedOut`, `SuggestionOut`, `SuggestResponse`.

This task has no test of its own — the schemas are exercised by Tasks 6 and 7. It exists as its own commit because both of those tasks consume it.

- [ ] **Step 1: Write the schemas**

Create `backend/app/schemas/category.py`:

```python
import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.models.category_rule import MatchType, RuleSource


class CategoryCreate(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: uuid.UUID | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    is_system: bool
    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    match_type: MatchType = MatchType.merchant_contains
    pattern: str
    category_id: uuid.UUID
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    account_id: uuid.UUID | None = None
    priority: int = 100


class RuleUpdate(BaseModel):
    match_type: MatchType | None = None
    pattern: str | None = None
    category_id: uuid.UUID | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    account_id: uuid.UUID | None = None
    priority: int | None = None


class RuleOut(BaseModel):
    id: uuid.UUID
    match_type: MatchType
    pattern: str
    category_id: uuid.UUID
    min_amount: Decimal | None
    max_amount: Decimal | None
    account_id: uuid.UUID | None
    priority: int
    source: RuleSource
    model_config = {"from_attributes": True}


class ReorderIn(BaseModel):
    """Rule ids in the order they should be tried. Priority is rewritten to match."""

    rule_ids: list[uuid.UUID]


class BackfillIn(BaseModel):
    only_uncategorized: bool = True


class UncategorizedOut(BaseModel):
    merchant: str
    count: int
    total: Decimal


class SuggestionOut(BaseModel):
    merchant: str
    category_id: uuid.UUID
    category_name: str


class SuggestResponse(BaseModel):
    suggestions: list[SuggestionOut]
    model: str
```

`CategoryOut.is_system` is computed, not a column. The router builds it with `household_id is None`; see Task 6.

- [ ] **Step 2: Type-check and commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/schemas/category.py
git commit -m "feat: schemas for categories and rules"
```

---

### Task 6: Category CRUD, with system rows immutable

**Files:**
- Modify: `backend/app/services/categories.py`
- Create: `backend/app/api/categories.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_categories_api.py`

**Interfaces:**
- Consumes: schemas from Task 5.
- Produces:
  - `class SystemCategoryImmutable(Exception)`
  - `categories.list_for(db, household_id) -> list[Category]` — system rows plus the household's own, ordered parent-first then by name
  - `categories.create(db, household_id, data: CategoryCreate) -> Category`
  - `categories.update(db, household_id, category_id, data: CategoryUpdate) -> Category | None` — raises `SystemCategoryImmutable`
  - `categories.delete(db, household_id, category_id) -> bool` — raises `SystemCategoryImmutable`
  - Router `categories.router`, prefix `/categories`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_categories_api.py`. Read `backend/tests/test_accounts.py` first and reuse its client fixture verbatim — do not build a second one.

```python
from app.services.categories import ensure_system_categories, system_category_id


def test_list_returns_system_taxonomy(client, db):
    ensure_system_categories(db)
    res = client.get("/categories")
    assert res.status_code == 200
    names = {c["name"] for c in res.json()}
    assert "Groceries" in names
    assert all(c["is_system"] for c in res.json() if c["name"] == "Groceries")


def test_create_custom_category(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/categories",
        json={"name": "Boat Fuel", "parent_id": str(system_category_id("Transport"))},
    )
    assert res.status_code == 200
    assert res.json()["is_system"] is False


def test_system_category_cannot_be_renamed(client, db):
    ensure_system_categories(db)
    res = client.patch(
        f"/categories/{system_category_id('Food & Drink/Groceries')}",
        json={"name": "Snacks"},
    )
    assert res.status_code == 403


def test_system_category_cannot_be_deleted(client, db):
    ensure_system_categories(db)
    res = client.delete(f"/categories/{system_category_id('Food & Drink/Groceries')}")
    assert res.status_code == 403


def test_custom_category_can_be_deleted(client, db):
    ensure_system_categories(db)
    created = client.post("/categories", json={"name": "Boat Fuel"}).json()
    assert client.delete(f"/categories/{created['id']}").status_code == 200
    assert created["id"] not in {c["id"] for c in client.get("/categories").json()}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Add CRUD to the service**

Append to `backend/app/services/categories.py`:

```python
class SystemCategoryImmutable(Exception):
    """System categories are shared by every install. They are read-only, always."""


def list_for(db: Session, household_id: uuid.UUID) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(
                (Category.household_id == household_id)
                | (Category.household_id.is_(None))
            )
            .order_by(Category.parent_id.nulls_first(), Category.name)
        )
    )


def get(db: Session, household_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
    row = db.get(Category, category_id)
    if row is None:
        return None
    if row.household_id is not None and row.household_id != household_id:
        return None
    return row


def create(db: Session, household_id: uuid.UUID, data: CategoryCreate) -> Category:
    row = Category(household_id=household_id, name=data.name, parent_id=data.parent_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, household_id: uuid.UUID, category_id: uuid.UUID, data: CategoryUpdate
) -> Category | None:
    row = get(db, household_id, category_id)
    if row is None:
        return None
    if row.household_id is None:
        raise SystemCategoryImmutable(str(category_id))
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, household_id: uuid.UUID, category_id: uuid.UUID) -> bool:
    row = get(db, household_id, category_id)
    if row is None:
        return False
    if row.household_id is None:
        raise SystemCategoryImmutable(str(category_id))
    db.delete(row)
    db.commit()
    return True
```

- [ ] **Step 4: Write the router**

Create `backend/app/api/categories.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import categories

router = APIRouter(prefix="/categories", tags=["categories"])


def _out(row: Category) -> CategoryOut:
    return CategoryOut(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        is_system=row.household_id is None,
    )


@router.get("", response_model=list[CategoryOut])
def list_categories(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[CategoryOut]:
    return [_out(c) for c in categories.list_for(db, hid)]


@router.post("", response_model=CategoryOut)
def create_category(
    body: CategoryCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryOut:
    return _out(categories.create(db, hid, body))


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryOut:
    try:
        row = categories.update(db, hid, category_id, body)
    except categories.SystemCategoryImmutable:
        raise HTTPException(status_code=403, detail="System categories cannot be edited")
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return _out(row)


@router.delete("/{category_id}")
def delete_category(
    category_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        removed = categories.delete(db, hid, category_id)
    except categories.SystemCategoryImmutable:
        raise HTTPException(status_code=403, detail="System categories cannot be deleted")
    if not removed:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "ok"}
```

In `backend/app/main.py`, add `categories` to the `from app.api import (...)` block and `app.include_router(categories.router)` alongside the others.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 6: Lint, type-check, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
```

```bash
git add backend/app/services/categories.py backend/app/api/categories.py \
        backend/app/main.py backend/tests/test_categories_api.py
git commit -m "feat: category CRUD, with the shared taxonomy locked"
```

---

### Task 7: Rule CRUD, reorder, preview, backfill, uncategorized

**Files:**
- Modify: `backend/app/services/categorization.py`
- Create: `backend/app/api/category_rules.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_categories_api.py` (append)

**Interfaces:**
- Consumes: `BadPattern`, `compile_pattern`, `rules_for`, `rule_matches`, `backfill`, `uncategorized_merchants` (Tasks 2–3); schemas from Task 5.
- Produces:
  - `create_rule(db, household_id, data: RuleCreate) -> CategoryRule` — raises `BadPattern`
  - `get_rule(db, household_id, rule_id) -> CategoryRule | None`
  - `update_rule(db, household_id, rule_id, data: RuleUpdate) -> CategoryRule | None` — raises `BadPattern`
  - `delete_rule(db, household_id, rule_id) -> bool`
  - `reorder(db, household_id, rule_ids: list[uuid.UUID]) -> int`
  - `preview(db, household_id, data: RuleCreate) -> int` — how many existing transactions the rule would match
  - Router `category_rules.router`, prefix `/category-rules`, plus `/categorization/*` routes on the same module-level router

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_categories_api.py`:

```python
def test_create_rule_and_list_in_priority_order(client, db):
    ensure_system_categories(db)
    groceries = str(system_category_id("Food & Drink/Groceries"))
    coffee = str(system_category_id("Food & Drink/Coffee"))
    client.post(
        "/category-rules",
        json={"pattern": "whole foods", "category_id": groceries, "priority": 50},
    )
    client.post(
        "/category-rules", json={"pattern": "blue bottle", "category_id": coffee, "priority": 10}
    )
    rules = client.get("/category-rules").json()
    assert [r["pattern"] for r in rules] == ["blue bottle", "whole foods"]


def test_invalid_regex_is_rejected_with_422(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/category-rules",
        json={
            "match_type": "merchant_regex",
            "pattern": "(unclosed",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert res.status_code == 422
    assert "regular expression" in res.json()["detail"]


def test_reorder_rewrites_priority(client, db):
    ensure_system_categories(db)
    groceries = str(system_category_id("Food & Drink/Groceries"))
    a = client.post("/category-rules", json={"pattern": "aaa", "category_id": groceries}).json()
    b = client.post("/category-rules", json={"pattern": "bbb", "category_id": groceries}).json()
    client.post("/category-rules/reorder", json={"rule_ids": [b["id"], a["id"]]})
    assert [r["pattern"] for r in client.get("/category-rules").json()] == ["bbb", "aaa"]


def test_preview_counts_matches_without_saving(client, db, household, account):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models.transaction import Transaction

    ensure_system_categories(db)
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
        )
    )
    db.commit()

    res = client.post(
        "/category-rules/preview",
        json={
            "pattern": "whole foods",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert res.json() == {"matches": 1}
    assert client.get("/category-rules").json() == []


def test_backfill_endpoint_reports_what_changed(client, db, household, account):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models.transaction import Transaction

    ensure_system_categories(db)
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS",
        )
    )
    db.commit()
    client.post(
        "/category-rules",
        json={
            "pattern": "whole foods",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert client.post("/categorization/backfill", json={}).json() == {"changed": 1}


def test_uncategorized_endpoint_rolls_up(client, db, household, account):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models.transaction import Transaction

    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-9.00"),
            currency="USD",
            merchant_raw="SHELL OIL #221",
        )
    )
    db.commit()
    rows = client.get("/categorization/uncategorized").json()
    assert rows[0]["merchant"] == "shell oil"
    assert rows[0]["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -v`
Expected: FAIL — 404 on `/category-rules`.

- [ ] **Step 3: Add rule CRUD to the service**

Append to `backend/app/services/categorization.py`:

```python
from app.schemas.category import RuleCreate, RuleUpdate


def create_rule(
    db: Session, household_id: uuid.UUID, data: RuleCreate
) -> CategoryRule:
    compile_pattern(data.match_type, data.pattern)
    row = CategoryRule(
        household_id=household_id,
        match_type=data.match_type,
        pattern=data.pattern,
        category_id=data.category_id,
        min_amount=data.min_amount,
        max_amount=data.max_amount,
        account_id=data.account_id,
        priority=data.priority,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_rule(
    db: Session, household_id: uuid.UUID, rule_id: uuid.UUID
) -> CategoryRule | None:
    return db.scalar(
        select(CategoryRule).where(
            CategoryRule.id == rule_id, CategoryRule.household_id == household_id
        )
    )


def update_rule(
    db: Session, household_id: uuid.UUID, rule_id: uuid.UUID, data: RuleUpdate
) -> CategoryRule | None:
    row = get_rule(db, household_id, rule_id)
    if row is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    compile_pattern(
        fields.get("match_type", row.match_type), fields.get("pattern", row.pattern)
    )
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete_rule(db: Session, household_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
    row = get_rule(db, household_id, rule_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def reorder(db: Session, household_id: uuid.UUID, rule_ids: list[uuid.UUID]) -> int:
    """Rewrite priority to match the given order. Ids not listed keep their place at
    the end, in their existing order."""
    by_id = {r.id: r for r in rules_for(db, household_id)}
    ordered = [by_id[i] for i in rule_ids if i in by_id]
    ordered += [r for r in by_id.values() if r.id not in set(rule_ids)]
    for index, row in enumerate(ordered):
        row.priority = (index + 1) * 10
    db.commit()
    return len(ordered)


def preview(db: Session, household_id: uuid.UUID, data: RuleCreate) -> int:
    """How many existing transactions a rule would match. Writes nothing."""
    compile_pattern(data.match_type, data.pattern)
    candidate = CategoryRule(
        household_id=household_id,
        match_type=data.match_type,
        pattern=data.pattern,
        category_id=data.category_id,
        min_amount=data.min_amount,
        max_amount=data.max_amount,
        account_id=data.account_id,
        priority=data.priority,
    )
    txns = db.scalars(
        select(Transaction).where(Transaction.household_id == household_id)
    )
    return sum(1 for t in txns if rule_matches(candidate, t))
```

`preview` builds a `CategoryRule` without adding it to the session, so nothing is persisted. If SQLAlchemy's autoflush complains, wrap the query in `with db.no_autoflush:`.

- [ ] **Step 4: Write the router**

Create `backend/app/api/category_rules.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.category_rule import CategoryRule
from app.schemas.category import (
    BackfillIn,
    ReorderIn,
    RuleCreate,
    RuleOut,
    RuleUpdate,
    UncategorizedOut,
)
from app.services import categorization

router = APIRouter(tags=["categorization"])


@router.get("/category-rules", response_model=list[RuleOut])
def list_rules(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[CategoryRule]:
    return categorization.rules_for(db, hid)


@router.post("/category-rules", response_model=RuleOut)
def create_rule(
    body: RuleCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryRule:
    try:
        return categorization.create_rule(db, hid, body)
    except categorization.BadPattern as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/category-rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryRule:
    try:
        row = categorization.update_rule(db, hid, rule_id, body)
    except categorization.BadPattern as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if row is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return row


@router.delete("/category-rules/{rule_id}")
def delete_rule(
    rule_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not categorization.delete_rule(db, hid, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "ok"}


@router.post("/category-rules/reorder")
def reorder_rules(
    body: ReorderIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"reordered": categorization.reorder(db, hid, body.rule_ids)}


@router.post("/category-rules/preview")
def preview_rule(
    body: RuleCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    try:
        return {"matches": categorization.preview(db, hid, body)}
    except categorization.BadPattern as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/categorization/backfill")
def run_backfill(
    body: BackfillIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {
        "changed": categorization.backfill(
            db, hid, only_uncategorized=body.only_uncategorized
        )
    }


@router.get("/categorization/uncategorized", response_model=list[UncategorizedOut])
def list_uncategorized(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[UncategorizedOut]:
    return [
        UncategorizedOut(merchant=m.merchant, count=m.count, total=m.total)
        for m in categorization.uncategorized_merchants(db, hid)
    ]
```

Route order matters: `/category-rules/reorder` and `/category-rules/preview` are declared before nothing that would shadow them, because the only path parameter route is `PATCH`/`DELETE` on `/{rule_id}` and these are `POST`. No conflict, but keep them in this order anyway.

In `backend/app/main.py`, add `category_rules` to the `from app.api import (...)` block and `app.include_router(category_rules.router)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -v`
Expected: PASS — 11 tests.

- [ ] **Step 6: Confirm tenancy**

Add to `backend/tests/test_tenancy.py`, following the shape of the checks already there: a rule created by household A must not appear in household B's `GET /category-rules`, and `PATCH`/`DELETE` on A's rule id from B must 404.

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_tenancy.py -v`
Expected: PASS.

- [ ] **Step 7: Lint, type-check, full suite, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app && .venv/Scripts/python -m pytest
```

```bash
git add backend/app/services/categorization.py backend/app/api/category_rules.py \
        backend/app/main.py backend/tests/test_categories_api.py backend/tests/test_tenancy.py
git commit -m "feat: rules you can read, reorder, and try before you save"
```

---

### Task 8: LLM rule suggestions that write nothing

**Files:**
- Modify: `backend/app/api/category_rules.py`
- Modify: `backend/app/services/categorization.py`
- Modify: `backend/app/providers/llm.py` (only if it has no JSON-returning entry point)
- Test: `backend/tests/test_categories_api.py` (append)

**Interfaces:**
- Consumes: `ClaudeProvider` and `LLMError` from `app.providers.llm` — read that file before writing this task and use its existing call signature rather than adding a parallel one.
- Produces:
  - `suggest_rules(db, household_id, provider) -> tuple[list[SuggestionOut], str]` — proposals plus the model name. Writes nothing.
  - `POST /categories/suggest` on the `category_rules` router.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_categories_api.py`:

```python
def test_suggest_returns_proposals_and_writes_nothing(client, db, household, account, monkeypatch):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models.transaction import Transaction
    from app.services import categorization

    ensure_system_categories(db)
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
        )
    )
    db.commit()

    def fake_complete(self, prompt, **kwargs):
        return '[{"merchant": "whole foods", "category": "Food & Drink/Groceries"}]'

    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.complete", fake_complete, raising=False
    )
    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.configured", property(lambda self: True)
    )

    res = client.post("/categories/suggest")
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"][0]["merchant"] == "whole foods"
    assert body["suggestions"][0]["category_name"] == "Groceries"
    # Nothing was written.
    assert categorization.rules_for(db, household.id) == []


def test_suggest_is_503_without_an_api_key(client, db, monkeypatch):
    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.configured", property(lambda self: False)
    )
    assert client.post("/categories/suggest").status_code == 503


def test_suggest_drops_a_category_the_model_invented(client, db, household, account, monkeypatch):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models.transaction import Transaction

    ensure_system_categories(db)
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS",
        )
    )
    db.commit()

    def fake_complete(self, prompt, **kwargs):
        return '[{"merchant": "whole foods", "category": "Nonsense/Invented"}]'

    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.complete", fake_complete, raising=False
    )
    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.configured", property(lambda self: True)
    )

    assert client.post("/categories/suggest").json()["suggestions"] == []
```

The `fake_complete` signature must match whatever `ClaudeProvider`'s real completion method is named and takes. Read `backend/app/providers/llm.py` and `backend/tests/test_insights.py` first — that test already fakes this provider, and this test must fake it the same way.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -k suggest -v`
Expected: FAIL — 404 on `/categories/suggest`.

- [ ] **Step 3: Implement the suggestion service**

Append to `backend/app/services/categorization.py`:

```python
import json

from app.schemas.category import SuggestionOut
from app.services.categories import TAXONOMY, system_category_id

_SUGGEST_PROMPT = """You are given a list of merchant names from a personal finance app,
and a fixed category taxonomy. For each merchant, choose the single best category.

Rules:
- Use only categories from the taxonomy, written exactly as "Group/Leaf".
- If no category fits a merchant, omit that merchant entirely.
- Reply with a JSON array and nothing else, in the form:
  [{"merchant": "<merchant, copied exactly>", "category": "Group/Leaf"}]

Taxonomy:
%(taxonomy)s

Merchants:
%(merchants)s
"""


def suggest_rules(
    db: Session, household_id: uuid.UUID, provider: object
) -> tuple[list[SuggestionOut], str]:
    """Ask the model to propose merchant → category pairs. Writes nothing, ever.

    The model sees merchant names and the taxonomy. It does not see amounts, dates,
    accounts, or balances — a name is all that is needed to guess a category, so that is
    all that leaves the machine.
    """
    merchants = [m.merchant for m in uncategorized_merchants(db, household_id, limit=60)]
    if not merchants:
        return [], getattr(provider, "model_name", "")

    taxonomy_text = "\n".join(
        f"{group}/{leaf}" for group, leaves in TAXONOMY.items() for leaf in leaves
    )
    prompt = _SUGGEST_PROMPT % {
        "taxonomy": taxonomy_text,
        "merchants": "\n".join(merchants),
    }
    raw = provider.complete(prompt)  # type: ignore[attr-defined]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], getattr(provider, "model_name", "")

    # Every proposal is checked against the taxonomy and against the merchants we
    # actually asked about. A category the model invented, or a merchant it hallucinated,
    # is dropped rather than surfaced for the user to tick without reading.
    valid_paths = {
        f"{group}/{leaf}": leaf for group, leaves in TAXONOMY.items() for leaf in leaves
    }
    asked = set(merchants)
    out: list[SuggestionOut] = []
    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict):
            continue
        merchant = item.get("merchant")
        path = item.get("category")
        if merchant not in asked or path not in valid_paths:
            continue
        out.append(
            SuggestionOut(
                merchant=merchant,
                category_id=system_category_id(path),
                category_name=valid_paths[path],
            )
        )
    return out, getattr(provider, "model_name", "")
```

Move `import json` into the module import block. `provider.complete(prompt)` is a placeholder for the real method — substitute whatever `ClaudeProvider` actually exposes, and type the parameter as that class rather than `object` if it imports cleanly without a cycle.

- [ ] **Step 4: Add the endpoint**

Append to `backend/app/api/category_rules.py`:

```python
@router.post("/categories/suggest", response_model=SuggestResponse)
def suggest(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> SuggestResponse:
    """Proposals only. Confirming one is a normal POST /category-rules by the client."""
    provider = ClaudeProvider()
    if not provider.configured:
        raise HTTPException(status_code=503, detail="No ANTHROPIC_API_KEY configured")
    try:
        suggestions, model = categorization.suggest_rules(db, hid, provider)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return SuggestResponse(suggestions=suggestions, model=model)
```

Add to that file's imports: `from app.providers.llm import ClaudeProvider, LLMError` and `SuggestResponse` to the schema import list.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_categories_api.py -v`
Expected: PASS — 14 tests.

- [ ] **Step 6: Lint, type-check, full suite, commit**

```bash
cd backend && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app && .venv/Scripts/python -m pytest
```

```bash
git add backend/app/services/categorization.py backend/app/api/category_rules.py \
        backend/tests/test_categories_api.py
git commit -m "feat: the model proposes categories, you decide which ones become rules"
```

---

### Task 9: Frontend data layer

**Files:**
- Create: `frontend/src/categories.ts`
- Modify: `frontend/src/data.ts`

**Interfaces:**
- Produces:
  - `type Category = { id: string; name: string; parent_id: string | null; is_system: boolean }`
  - `type Rule = { id: string; match_type: MatchType; pattern: string; category_id: string; min_amount: string | null; max_amount: string | null; account_id: string | null; priority: number; source: "user" | "suggested" }`
  - `type MatchType = "merchant_contains" | "merchant_exact" | "merchant_regex"`
  - `type Uncategorized = { merchant: string; count: number; total: string }`
  - `type Suggestion = { merchant: string; category_id: string; category_name: string }`
  - `useCategories()`, `useCategoryMap()`, `useRules()`, `useUncategorized()`
  - `useCreateRule()`, `useDeleteRule()`, `useReorderRules()`, `useBackfill()`, `useSuggest()`
- Consumes: `apiFetch` from `./api/client`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/categories.test.tsx` with the data-layer test only; component tests come in Tasks 10–11. Copy the QueryClient wrapper pattern from `frontend/src/recurring.test.tsx`.

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCategoryMap } from "./categories";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.mocked(apiFetch).mockReset());

describe("useCategoryMap", () => {
  it("labels a leaf with its group", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
      { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
    ]);
    const { result } = renderHook(() => useCategoryMap(), { wrapper });
    await waitFor(() => expect(result.current.get("c1")).toBe("Food & Drink · Groceries"));
  });

  it("labels a top-level category with just its name", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Transfers", parent_id: null, is_system: true },
    ]);
    const { result } = renderHook(() => useCategoryMap(), { wrapper });
    await waitFor(() => expect(result.current.get("g1")).toBe("Transfers"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- categories`
Expected: FAIL — cannot resolve `./categories`.

- [ ] **Step 3: Write the data layer**

Create `frontend/src/categories.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type MatchType = "merchant_contains" | "merchant_exact" | "merchant_regex";

export type Category = {
  id: string;
  name: string;
  parent_id: string | null;
  is_system: boolean;
};

export type Rule = {
  id: string;
  match_type: MatchType;
  pattern: string;
  category_id: string;
  min_amount: string | null;
  max_amount: string | null;
  account_id: string | null;
  priority: number;
  source: "user" | "suggested";
};

export type Uncategorized = { merchant: string; count: number; total: string };
export type Suggestion = { merchant: string; category_id: string; category_name: string };

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => apiFetch<Category[]>("/categories"),
    // The taxonomy changes when the user edits it and not otherwise.
    staleTime: 5 * 60 * 1000,
  });
}

/** id → "Group · Leaf", for labelling a transaction row without a join on the server. */
export function useCategoryMap(): Map<string, string> {
  const { data = [] } = useCategories();
  const byId = new Map(data.map((c) => [c.id, c]));
  return new Map(
    data.map((c) => {
      const parent = c.parent_id ? byId.get(c.parent_id) : undefined;
      return [c.id, parent ? `${parent.name} · ${c.name}` : c.name];
    }),
  );
}

export function useRules() {
  return useQuery({ queryKey: ["category-rules"], queryFn: () => apiFetch<Rule[]>("/category-rules") });
}

export function useUncategorized() {
  return useQuery({
    queryKey: ["uncategorized"],
    queryFn: () => apiFetch<Uncategorized[]>("/categorization/uncategorized"),
  });
}

/** Anything that changes categorization invalidates the same three things. */
function useCategorizationInvalidator() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["category-rules"] });
    qc.invalidateQueries({ queryKey: ["uncategorized"] });
    qc.invalidateQueries({ queryKey: ["transactions"] });
  };
}

export type NewRule = {
  pattern: string;
  category_id: string;
  match_type?: MatchType;
  priority?: number;
};

export function useCreateRule() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (rule: NewRule) =>
      apiFetch<Rule>("/category-rules", { method: "POST", body: JSON.stringify(rule) }),
    onSuccess: invalidate,
  });
}

export function useDeleteRule() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/category-rules/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useReorderRules() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (rule_ids: string[]) =>
      apiFetch("/category-rules/reorder", {
        method: "POST",
        body: JSON.stringify({ rule_ids }),
      }),
    onSuccess: invalidate,
  });
}

export function useBackfill() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (only_uncategorized: boolean) =>
      apiFetch<{ changed: number }>("/categorization/backfill", {
        method: "POST",
        body: JSON.stringify({ only_uncategorized }),
      }),
    onSuccess: invalidate,
  });
}

export function useSuggest() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ suggestions: Suggestion[]; model: string }>("/categories/suggest", {
        method: "POST",
      }),
  });
}
```

In `frontend/src/data.ts`, add `category_id: string | null;` to the `Txn` type.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- categories`
Expected: PASS — 2 tests.

- [ ] **Step 5: Typecheck, lint, commit**

```bash
cd frontend && npm run typecheck && npm run lint
```

```bash
git add frontend/src/categories.ts frontend/src/categories.test.tsx frontend/src/data.ts
git commit -m "feat: category hooks for the web client"
```

---

### Task 10: Category on the transaction row, and the "always" prompt

**Files:**
- Create: `frontend/src/categories.tsx`
- Modify: `frontend/src/transactions.tsx`
- Test: `frontend/src/categories.test.tsx` (append)

**Interfaces:**
- Consumes: `useCategories`, `useCategoryMap`, `useCreateRule` (Task 9).
- Produces: `CategoryPicker({ value, onChange, ariaLabel })` — a `<select>` of the taxonomy, grouped with `<optgroup>`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/categories.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { CategoryPicker } from "./categories";

describe("CategoryPicker", () => {
  it("groups leaves under their parent and reports the chosen id", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
      { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
    ]);
    const onChange = vi.fn();
    render(<CategoryPicker value={null} onChange={onChange} ariaLabel="Category" />, {
      wrapper,
    });
    const select = await screen.findByLabelText("Category");
    fireEvent.change(select, { target: { value: "c1" } });
    expect(onChange).toHaveBeenCalledWith("c1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- categories`
Expected: FAIL — `CategoryPicker` is not exported.

- [ ] **Step 3: Write the picker**

Create `frontend/src/categories.tsx`:

```tsx
import { useCategories } from "./categories";

export function CategoryPicker({
  value,
  onChange,
  ariaLabel = "Category",
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  ariaLabel?: string;
}) {
  const { data = [] } = useCategories();
  const groups = data.filter((c) => c.parent_id === null);

  return (
    <select
      aria-label={ariaLabel}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="text-[13px]"
    >
      <option value="">Uncategorized</option>
      {groups.map((g) => {
        const leaves = data.filter((c) => c.parent_id === g.id);
        // A group with no leaves is selectable in its own right — "Transfers" may never
        // need splitting, and forcing a leaf under it would be busywork.
        return leaves.length === 0 ? (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ) : (
          <optgroup key={g.id} label={g.name}>
            {leaves.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}
```

Both `categories.ts` and `categories.tsx` exist with the same base name. Vite resolves `./categories` to the `.ts` file, so `categories.tsx` importing `./categories` gets the hooks — which is what is wanted. To avoid the ambiguity biting a reader, add at the top of `categories.tsx`:

```tsx
// Hooks and types live in categories.ts; this file is the components over them.
```

- [ ] **Step 4: Add the category cell and the "always" prompt**

In `frontend/src/transactions.tsx`, change `TxnRows` to accept the picker and prompt. Replace the component with:

```tsx
export function TxnRows({ txns }: { txns: Txn[] }) {
  return (
    <table className="w-full">
      <tbody>
        {txns.map((t, i) => (
          <TxnRow key={t.id} txn={t} index={i} />
        ))}
      </tbody>
    </table>
  );
}

function TxnRow({ txn, index }: { txn: Txn; index: number }) {
  const qc = useQueryClient();
  const createRule = useCreateRule();
  const [askAbout, setAskAbout] = useState<string | null>(null);

  const setCategory = useMutation({
    mutationFn: (categoryId: string | null) =>
      apiFetch(`/transactions/${txn.id}`, {
        method: "PATCH",
        body: JSON.stringify({ category_id: categoryId }),
      }),
    onSuccess: (_data, categoryId) => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["uncategorized"] });
      // Offer the rule rather than writing one: a one-off recategorization is common,
      // and a rule the user didn't ask for is a rule they have to find and delete.
      if (categoryId) setAskAbout(categoryId);
    },
  });

  return (
    <>
      <tr
        className="rise border-b border-line/60 transition-colors last:border-0 hover:bg-[rgba(237,234,228,0.02)]"
        style={{ "--d": `${Math.min(index, 12) * 30}ms` } as React.CSSProperties}
      >
        <td className="tnum w-24 py-3 text-[13px] text-muted">{shortDate(txn.posted_at)}</td>
        <td className="py-3 text-sm">{txn.merchant_raw}</td>
        <td className="py-3">
          <CategoryPicker
            value={txn.category_id}
            onChange={(id) => setCategory.mutate(id)}
            ariaLabel={`Category for ${txn.merchant_raw}`}
          />
        </td>
        <td
          className={`tnum py-3 text-right text-sm ${
            Number(txn.amount) > 0 ? "text-acid" : "text-bone"
          }`}
        >
          {Number(txn.amount) > 0 ? `+${usd(txn.amount)}` : usd(txn.amount)}
        </td>
      </tr>
      {askAbout && (
        <tr>
          <td colSpan={4} className="pb-3 text-[13px] text-muted">
            Always categorize “{txn.merchant_raw}” this way?{" "}
            <button
              className="text-acid"
              onClick={() => {
                createRule.mutate({ pattern: txn.merchant_raw, category_id: askAbout });
                setAskAbout(null);
              }}
            >
              Make it a rule
            </button>{" "}
            <button className="ml-2" onClick={() => setAskAbout(null)}>
              No
            </button>
          </td>
        </tr>
      )}
    </>
  );
}
```

Add the imports this needs at the top of `transactions.tsx`:

```tsx
import { CategoryPicker } from "./categories";
import { useCreateRule } from "./categories";
```

`useMutation`, `useQueryClient`, `useState`, `apiFetch`, `shortDate`, and `usd` are already imported in that file.

The rule is created with `pattern: txn.merchant_raw` and the default `merchant_contains`. The backend normalizes the pattern through `merchant_key`, so "WHOLE FOODS #4471" becomes "whole foods" and matches the other stores too — which is the behaviour a user asking for "always" wants.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS. `frontend/src/transactions.test.tsx` will need its mocks extended — it renders `TxnRows`, which now calls `useCategories`. Add `/categories` to whatever `apiFetch` mock that file uses, returning `[]`.

- [ ] **Step 6: Typecheck, lint, commit**

```bash
cd frontend && npm run typecheck && npm run lint
```

```bash
git add frontend/src/categories.tsx frontend/src/categories.test.tsx \
        frontend/src/transactions.tsx frontend/src/transactions.test.tsx
git commit -m "feat: set a category on a row, and be asked before it becomes a rule"
```

---

### Task 11: The Rules and Uncategorized cards

**Files:**
- Modify: `frontend/src/categories.tsx`
- Modify: `frontend/src/pages/TransactionsPage.tsx`
- Test: `frontend/src/categories.test.tsx` (append)

**Interfaces:**
- Consumes: `useRules`, `useDeleteRule`, `useReorderRules`, `useBackfill`, `useUncategorized`, `useSuggest`, `useCreateRule`, `useCategoryMap` (Task 9); `CategoryPicker` (Task 10).
- Produces: `RulesCard()`, `UncategorizedCard()`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/categories.test.tsx`:

```tsx
import { RulesCard } from "./categories";

describe("RulesCard", () => {
  it("lists rules in priority order with their category label", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/categories")
        return [
          { id: "g1", name: "Food & Drink", parent_id: null, is_system: true },
          { id: "c1", name: "Groceries", parent_id: "g1", is_system: true },
        ];
      if (path === "/category-rules")
        return [
          {
            id: "r1",
            match_type: "merchant_contains",
            pattern: "whole foods",
            category_id: "c1",
            min_amount: null,
            max_amount: null,
            account_id: null,
            priority: 10,
            source: "user",
          },
        ];
      return [];
    });
    render(<RulesCard />, { wrapper });
    expect(await screen.findByText("whole foods")).toBeInTheDocument();
    expect(await screen.findByText("Food & Drink · Groceries")).toBeInTheDocument();
  });

  it("shows an empty state when there are no rules", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<RulesCard />, { wrapper });
    expect(await screen.findByText(/No rules yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- categories`
Expected: FAIL — `RulesCard` is not exported.

- [ ] **Step 3: Write the cards**

Append to `frontend/src/categories.tsx`:

```tsx
import { useState } from "react";
import {
  useBackfill,
  useCategoryMap,
  useCreateRule,
  useDeleteRule,
  useReorderRules,
  useRules,
  useSuggest,
  useUncategorized,
  type Suggestion,
} from "./categories";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

export function RulesCard() {
  const { data: rules = [], isLoading } = useRules();
  const labels = useCategoryMap();
  const remove = useDeleteRule();
  const reorder = useReorderRules();
  const backfill = useBackfill();
  const create = useCreateRule();
  const [pattern, setPattern] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);

  // ponytail: move-up/move-down buttons rather than drag-and-drop. Ordering a handful
  // of rules is a two-click job; a drag library is a dependency and a touch-target
  // problem. Revisit if someone accumulates enough rules to make this tedious.
  const move = (index: number, delta: number) => {
    const next = [...rules];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next.map((r) => r.id));
  };

  return (
    <Card className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium">Rules</h2>
        <button onClick={() => backfill.mutate(true)} className="text-[13px] text-acid">
          {backfill.isPending ? "Applying…" : "Apply to history"}
        </button>
      </div>

      {backfill.data && (
        <p className="mb-3 text-[13px] text-muted">
          Categorized {backfill.data.changed} transaction
          {backfill.data.changed === 1 ? "" : "s"}.
        </p>
      )}

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!pattern.trim() || !categoryId) return;
          create.mutate(
            { pattern, category_id: categoryId },
            { onSuccess: () => setPattern("") },
          );
        }}
      >
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="label">Merchant contains</span>
          <input
            aria-label="Merchant contains"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="whole foods"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Category</span>
          <CategoryPicker value={categoryId} onChange={setCategoryId} ariaLabel="Rule category" />
        </label>
        <button type="submit" disabled={create.isPending}>
          Add rule
        </button>
      </form>

      {create.isError && (
        <p className="mb-3 text-[13px] text-red-400">{(create.error as Error).message}</p>
      )}

      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : rules.length === 0 ? (
        <Empty>No rules yet. Add one above, or set a category on a transaction.</Empty>
      ) : (
        <table className="w-full">
          <tbody>
            {rules.map((r, i) => (
              <tr key={r.id} className="border-b border-line/60 last:border-0">
                <td className="py-2 text-sm">{r.pattern}</td>
                <td className="py-2 text-[13px] text-muted">
                  {labels.get(r.category_id) ?? "—"}
                </td>
                <td className="py-2 text-right text-[13px]">
                  <button aria-label={`Move ${r.pattern} up`} onClick={() => move(i, -1)}>
                    ↑
                  </button>
                  <button
                    aria-label={`Move ${r.pattern} down`}
                    className="ml-2"
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </button>
                  <button
                    aria-label={`Delete ${r.pattern}`}
                    className="ml-3 text-muted"
                    onClick={() => remove.mutate(r.id)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export function UncategorizedCard() {
  const { data: rows = [] } = useUncategorized();
  const suggest = useSuggest();
  const create = useCreateRule();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const toggle = (merchant: string) => {
    const next = new Set(picked);
    next.has(merchant) ? next.delete(merchant) : next.add(merchant);
    setPicked(next);
  };

  const accept = (suggestions: Suggestion[]) => {
    for (const s of suggestions.filter((s) => picked.has(s.merchant))) {
      create.mutate({ pattern: s.merchant, category_id: s.category_id });
    }
    setPicked(new Set());
  };

  if (rows.length === 0) return null;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium">Uncategorized</h2>
        <button
          onClick={() => suggest.mutate()}
          disabled={suggest.isPending}
          className="text-[13px] text-acid"
        >
          {suggest.isPending ? "Asking…" : "Suggest categories"}
        </button>
      </div>

      {suggest.isError && (
        <p className="mb-3 text-[13px] text-muted">
          {(suggest.error as Error).message}
        </p>
      )}

      {suggest.data ? (
        <>
          <p className="mb-3 text-[13px] text-muted">
            Proposed by {suggest.data.model}. Nothing is saved until you accept.
          </p>
          <table className="w-full">
            <tbody>
              {suggest.data.suggestions.map((s) => (
                <tr key={s.merchant} className="border-b border-line/60 last:border-0">
                  <td className="py-2">
                    <input
                      type="checkbox"
                      aria-label={`Accept ${s.merchant}`}
                      checked={picked.has(s.merchant)}
                      onChange={() => toggle(s.merchant)}
                    />
                  </td>
                  <td className="py-2 text-sm">{s.merchant}</td>
                  <td className="py-2 text-[13px] text-muted">{s.category_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            className="mt-3"
            disabled={picked.size === 0}
            onClick={() => accept(suggest.data.suggestions)}
          >
            Create {picked.size} rule{picked.size === 1 ? "" : "s"}
          </button>
        </>
      ) : (
        <table className="w-full">
          <tbody>
            {rows.slice(0, 15).map((r) => (
              <tr key={r.merchant} className="border-b border-line/60 last:border-0">
                <td className="py-2 text-sm">{r.merchant}</td>
                <td className="tnum py-2 text-[13px] text-muted">{r.count}×</td>
                <td className="tnum py-2 text-right text-[13px]">{usd(r.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
```

Merge the `import { useState } from "react";` and the `./categories` import block into the imports already at the top of the file rather than leaving a second import block mid-file.

- [ ] **Step 4: Mount them on the page**

In `frontend/src/pages/TransactionsPage.tsx`, add the import and render both cards after the History card:

```tsx
import { RulesCard, UncategorizedCard } from "../categories";
```

```tsx
      <Card className="mt-4" delay={120}>
        <h2 className="mb-4 text-sm font-medium">History</h2>
        <TransactionList />
      </Card>

      <UncategorizedCard />
      <RulesCard />
```

`UncategorizedCard` returns `null` when there is nothing uncategorized, so a tidy install sees no dead card.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 6: Typecheck, lint, commit**

```bash
cd frontend && npm run typecheck && npm run lint
```

```bash
git add frontend/src/categories.tsx frontend/src/categories.test.tsx \
        frontend/src/pages/TransactionsPage.tsx
git commit -m "feat: a rules list you can reorder and an inbox of what's unsorted"
```

---

### Task 12: End-to-end check and documentation

**Files:**
- Create or modify: `frontend/e2e/categorization.spec.ts` (match the existing e2e file naming — check `frontend/e2e/` first)
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the Playwright flow**

Read an existing spec in `frontend/e2e/` and follow its setup. The flow:

```ts
import { expect, test } from "@playwright/test";

test("a rule categorizes an imported transaction", async ({ page }) => {
  await page.goto("/transactions");

  // Create the rule.
  await page.getByLabel("Merchant contains").fill("whole foods");
  await page.getByLabel("Rule category").selectOption({ label: "Groceries" });
  await page.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByText("whole foods")).toBeVisible();

  // Add a matching transaction by hand.
  await page.getByLabel("Date").fill("2026-07-01");
  await page.getByLabel("Merchant").fill("WHOLE FOODS #4471");
  await page.getByLabel("Amount").fill("-42.00");
  await page.getByRole("button", { name: /add/i }).click();

  // It arrives categorized.
  await expect(
    page.getByLabel("Category for WHOLE FOODS #4471"),
  ).toHaveValue(/.+/);
});
```

The "Amount" label and the submit button name must match what `NewTransactionForm` actually renders — read the rest of `frontend/src/transactions.tsx` and use the real strings.

- [ ] **Step 2: Run the e2e suite**

Run: `docker compose up -d` then `cd frontend && npm run dev` in one terminal and `npm run e2e` in another.
Expected: PASS.

- [ ] **Step 3: Update the README**

In `README.md`, under "What's here", add:

```markdown
- **Categories** — a rule list that sorts transactions as they arrive, from CSV import or
  from a bank sync. Rules match on merchant, amount, and account; the first one in the
  list wins, and you can reorder them. Nothing is a black box: every category on a
  transaction traces to a rule you can open.
```

In the "Not here yet" list, delete `categorization rules` and `Budgets` stays. The line currently reads:

```markdown
- Budgets, categorization rules, investments holdings, reports. See the roadmap in the
  design spec.
```

Replace with:

```markdown
- Budgets, reports. See the roadmap in `docs/superpowers/specs/2026-07-30-origin-parity-design.md`.
```

Investments holdings shipped already; that line was stale.

In the "AI assistant" section, add after the existing paragraphs:

```markdown
The assistant can also propose categories for merchants it hasn't seen sorted. That call
sends merchant *names* and the category list — no amounts, no dates, no accounts — and
its proposals are written only for the ones you tick.
```

- [ ] **Step 4: Update the changelog**

Add an entry to `CHANGELOG.md` following the format already in that file: categorization rules, system taxonomy, automatic categorization at import and sync, backfill, and optional LLM rule suggestions.

- [ ] **Step 5: Full gate**

```bash
cd backend && .venv/Scripts/python -m pytest && .venv/Scripts/python -m ruff check app tests && .venv/Scripts/python -m mypy app
cd ../frontend && npm test && npm run typecheck && npm run lint
```

Every one must pass. Do not claim P1 complete on a partial run — paste the actual output.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/categorization.spec.ts README.md CHANGELOG.md
git commit -m "docs: categorization ships; the README's stale gaps go with it"
```

---

## Self-Review

**Spec coverage** — every P1 requirement from `2026-07-30-origin-parity-design.md` §5:

| Spec requirement | Task |
|---|---|
| System taxonomy, ~12 groups / ~50 leaves, `household_id IS NULL` | 1 |
| `category_rules` table with all listed columns | 1 |
| Match on `merchant_normalized` falling back to `merchant_raw` | 2 (`_merchant_of`) |
| Every non-null condition must hold | 2 |
| `apply_rules` / `categorize_new` | 3 (`apply_to`) + 4 (call sites) |
| `backfill` with `only_uncategorized` defaulting true | 3 |
| `uncategorized_merchants` | 3 |
| Categorize at CSV import and at sync | 4 |
| All 12 listed endpoints | 6, 7, 8 |
| System categories immutable | 6 |
| Regex validated, pattern length capped | 2, 7 |
| LLM suggests, writes nothing until confirmed | 8 |
| Transactions page: category column, inline edit, "always" prompt | 10 |
| Rules page: ordered list, reprioritize, test-against-history | 11 (`RulesCard`) + 7 (`preview`) |
| Uncategorized panel with suggest flow | 11 |
| Index on `(household_id, category_id, posted_at)` | 1 |

**Deviation from the spec, recorded:** the spec calls for a "new Rules page". This plan puts the rules UI on the Transactions page instead. `Shell.tsx` documents five tabs as the hard ceiling for the mobile bar, and rules are only ever reached from looking at transactions. Same functionality, no navigation debt.

**`preview` is reachable but not yet wired to a button.** Task 7 ships the endpoint and its test; `RulesCard` in Task 11 does not call it. The spec asks for a "test against my history" button — it is the one piece of P1 UI deliberately deferred, because the add-rule form is a single line and a preview step in front of it is friction for a two-second undo. Add it if rule-writing turns out to be error-prone in use.

**Type consistency** — `apply_to` (not `apply_rules`, which is what the spec prose called it) is used consistently in Tasks 3 and 4. `system_category_id` takes a path string in Tasks 1, 8, and every test. `CategoryPicker`'s props (`value`, `onChange`, `ariaLabel`) match between Tasks 10 and 11. `useCreateRule` takes `NewRule` in Tasks 9, 10, and 11.

**Placeholder scan** — one intentional stub remains: the sync test body in Task 4 Step 1 is a docstring with instructions rather than code, because the fake provider's merchant strings live in `test_sync.py` and must be read from there. The step says so explicitly and says to replace it before running.
