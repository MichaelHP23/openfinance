"""Monthly budgets: an amount per category per month, with a purely arithmetic read
model layered on top in later tasks — pace and rollover carry, no ML, no LLM.

`month` is always the first of the calendar month; the date column IS the period, so
there is no period-type or period-length concept anywhere in this module.
"""

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.services import categories


class UnknownCategory(Exception):
    """A budget can only point at a category this household can actually see."""


class BadMonth(Exception):
    """A month path segment that isn't a parseable "YYYY-MM"."""


def parse_month(value: str) -> date:
    """"YYYY-MM" -> the first of that month. Raises BadMonth, never a bare ValueError,
    so the router can turn a malformed URL segment into a 422 instead of a 500."""
    parts = value.split("-")
    if len(parts) != 2:
        raise BadMonth(value)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise BadMonth(value) from exc


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


def _prior_month(d: date) -> date:
    if d.month == 1:
        return d.replace(year=d.year - 1, month=12)
    return d.replace(month=d.month - 1)


@dataclass
class BudgetItem:
    category_id: uuid.UUID
    amount: Decimal
    rollover: bool = False


def list_budgets(db: Session, household_id: uuid.UUID, month: date) -> list[Budget]:
    month = _first_of_month(month)
    return list(
        db.scalars(
            select(Budget).where(
                Budget.household_id == household_id, Budget.month == month
            )
        )
    )


def _get_budget(
    db: Session, household_id: uuid.UUID, category_id: uuid.UUID, month: date
) -> Budget | None:
    return db.scalar(
        select(Budget).where(
            Budget.household_id == household_id,
            Budget.category_id == category_id,
            Budget.month == month,
        )
    )


def upsert(
    db: Session, household_id: uuid.UUID, month: date, items: list[BudgetItem]
) -> list[Budget]:
    """Insert or update one row per item. Idempotent: calling this twice with the same
    items leaves the same rows rather than duplicating them or raising — the unique
    constraint on (household_id, category_id, month) is what a period-as-a-date-column
    buys for free."""
    month = _first_of_month(month)
    out: list[Budget] = []
    for item in items:
        if categories.get(db, household_id, item.category_id) is None:
            raise UnknownCategory(str(item.category_id))
        row = _get_budget(db, household_id, item.category_id, month)
        if row is None:
            row = Budget(
                household_id=household_id,
                category_id=item.category_id,
                month=month,
                amount=item.amount,
                rollover=item.rollover,
            )
            db.add(row)
        else:
            row.amount = item.amount
            row.rollover = item.rollover
        out.append(row)
    db.commit()
    for row in out:
        db.refresh(row)
    return out


def _leaf_categories(db: Session, household_id: uuid.UUID) -> list[Category]:
    """Categories nothing else is a child of — a real leaf, or a childless top-level
    custom category. `CategoryPicker` on the frontend only ever offers one of these as a
    selectable value (a group with leaves renders as an <optgroup> label, never an
    option), so these are the only categories a transaction can actually land in. A
    parent group would always show a zero row here and add nothing but clutter.

    ponytail: if a transaction is ever filed directly under a group id through some path
    other than the picker, its spend will not appear in `status`. Nothing in this app
    currently writes a group id onto a transaction; revisit if that changes.
    """
    all_cats = categories.list_for(db, household_id)
    parents = {c.parent_id for c in all_cats if c.parent_id is not None}
    return [c for c in all_cats if c.id not in parents]


def _actuals_for_month(
    db: Session, household_id: uuid.UUID, month: date
) -> dict[uuid.UUID, Decimal]:
    """Spend per category for the month, sign-flipped: transactions store outflow as a
    negative amount, but a budget is stated as the positive number a person budgets, so
    a $30 grocery run should read as actual=30.00, not -30.00."""
    # posted_at is TIMESTAMP WITH TIME ZONE; a bare `date` gets coerced to timestamptz
    # at midnight in the session's TimeZone setting, not UTC, which would attribute
    # boundary transactions to the wrong month whenever the DB's TimeZone isn't UTC.
    # Every other range query in this codebase (digest.py, recurring.py, investments.py)
    # passes a tz-aware datetime for the same reason.
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    next_month = _next_month(month)
    end = datetime(next_month.year, next_month.month, 1, tzinfo=UTC)
    rows = db.execute(
        select(Transaction.category_id, func.sum(Transaction.amount))
        .where(
            Transaction.household_id == household_id,
            Transaction.category_id.is_not(None),
            Transaction.posted_at >= start,
            Transaction.posted_at < end,
        )
        .group_by(Transaction.category_id)
    )
    return {cat_id: -total for cat_id, total in rows}


def _elapsed_fraction(month: date, today: date) -> float:
    """How far through `month` `today` is, as a fraction in [0, 1]. A month entirely in
    the past reads 1.0; one that has not started yet reads 0.0 — both avoid a pace
    computation that would otherwise divide by a fraction of zero or overshoot 1."""
    if today < month:
        return 0.0
    if today >= _next_month(month):
        return 1.0
    days_in_month = monthrange(month.year, month.month)[1]
    elapsed_days = min((today - month).days + 1, days_in_month)
    return elapsed_days / days_in_month


@dataclass
class CategoryBudgetStatus:
    category_id: uuid.UUID
    category_name: str
    budgeted: Decimal
    carry_in: Decimal
    effective_budget: Decimal
    actual: Decimal
    remaining: Decimal
    pace: float | None
    rollover: bool


# A chain of rollover=true rows could in principle walk back through a household's
# entire budget history. Twenty-four months is far past any budget anyone keeps rolling
# over on purpose, and an unbounded backward walk against arbitrary history is exactly
# the kind of unbounded work PLAN-CONSTRAINTS.md keeps out of a request handler.
_MAX_ROLLOVER_LOOKBACK = 24


# Keyed by month -> {category_id: actual}, one entry per distinct month touched while
# walking a rollover chain. Without this, `rollover_carry` re-runs a full household-wide
# GROUP BY aggregate for every (category, month) pair in the chain even though only the
# distinct months matter — C rollover categories over a D-month chain would otherwise
# cost C×D queries for D actually-distinct months.
_ActualsMemo = dict[date, dict[uuid.UUID, Decimal]]


def _carry_into(
    db: Session,
    household_id: uuid.UUID,
    category_id: uuid.UUID,
    month: date,
    *,
    _depth: int = 0,
    _actuals_memo: _ActualsMemo,
) -> Decimal:
    """Unspent *effective* budget from the month before `month`, if `month`'s own row
    opted in. Recomputed from history every call, never stored — see `rollover_carry`."""
    if _depth >= _MAX_ROLLOVER_LOOKBACK:
        return Decimal(0)
    row = _get_budget(db, household_id, category_id, month)
    if row is None or not row.rollover:
        return Decimal(0)
    prior_month = _prior_month(month)
    prior = _get_budget(db, household_id, category_id, prior_month)
    if prior is None:
        return Decimal(0)
    prior_carry = _carry_into(
        db,
        household_id,
        category_id,
        prior_month,
        _depth=_depth + 1,
        _actuals_memo=_actuals_memo,
    )
    prior_actual = _actual_for(db, household_id, category_id, prior_month, _actuals_memo)
    return prior.amount + prior_carry - prior_actual


def _actual_for(
    db: Session,
    household_id: uuid.UUID,
    category_id: uuid.UUID,
    month: date,
    _actuals_memo: _ActualsMemo,
) -> Decimal:
    if month not in _actuals_memo:
        _actuals_memo[month] = _actuals_for_month(db, household_id, month)
    return _actuals_memo[month].get(category_id, Decimal(0))


def rollover_carry(
    db: Session,
    household_id: uuid.UUID,
    month: date,
    *,
    budget_rows: list[Budget] | None = None,
) -> dict[uuid.UUID, Decimal]:
    """Carry-in for every rollover=true row in `month`. Read-only: nothing here writes
    a row. A household that never checks the rollover box gets an empty dict back, and
    every number `status` shows it is exactly what was typed into `amount`.

    `budget_rows` lets a caller that already fetched `month`'s budgets (e.g. `status`)
    pass them straight in instead of paying for the same `list_budgets` query twice.
    """
    month = _first_of_month(month)
    rows = budget_rows if budget_rows is not None else list_budgets(db, household_id, month)
    out: dict[uuid.UUID, Decimal] = {}
    actuals_memo: _ActualsMemo = {}
    for row in rows:
        if row.rollover:
            out[row.category_id] = _carry_into(
                db, household_id, row.category_id, month, _actuals_memo=actuals_memo
            )
    return out


def status(
    db: Session, household_id: uuid.UUID, month: date, *, today: date | None = None
) -> list[CategoryBudgetStatus]:
    """Budgeted, actual, remaining, and pace for every leaf category — budgeted or not,
    so an unbudgeted category with real spend still shows up.

    Pace is (fraction of the effective budget spent) / (fraction of the month elapsed):
    above 1 means spending is outrunning the calendar, below 1 means it is on track or
    under. It is a ratio, not an amount of money, so unlike every other field on this
    dataclass it is a plain `float` — do not change it to `Decimal`.

    `carry_in` is computed by `rollover_carry()` from stored budget history and actual
    spend — it is zero only for rows where rollover is false or no prior month exists.
    """
    month = _first_of_month(month)
    today = today or datetime.now(tz=UTC).date()
    cats = _leaf_categories(db, household_id)
    budget_rows = list_budgets(db, household_id, month)
    budgets_by_cat = {b.category_id: b for b in budget_rows}
    actuals = _actuals_for_month(db, household_id, month)
    carries = rollover_carry(db, household_id, month, budget_rows=budget_rows)
    elapsed = _elapsed_fraction(month, today)

    out = []
    for cat in cats:
        row = budgets_by_cat.get(cat.id)
        budgeted = row.amount if row else Decimal(0)
        rollover = row.rollover if row else False
        carry_in = carries.get(cat.id, Decimal(0))
        effective = budgeted + carry_in
        actual = actuals.get(cat.id, Decimal(0))
        remaining = effective - actual
        pace = None
        if effective > 0 and elapsed > 0:
            pace = (float(actual) / float(effective)) / elapsed
        out.append(
            CategoryBudgetStatus(
                category_id=cat.id,
                category_name=cat.name,
                budgeted=budgeted,
                carry_in=carry_in,
                effective_budget=effective,
                actual=actual,
                remaining=remaining,
                pace=pace,
                rollover=rollover,
            )
        )
    return out


@dataclass
class BudgetSuggestion:
    category_id: uuid.UUID
    category_name: str
    amount: Decimal


def _round_to_5(value: Decimal) -> Decimal:
    return (value / 5).to_integral_value(rounding=ROUND_HALF_UP) * 5


def suggest(db: Session, household_id: uuid.UUID, month: date) -> list[BudgetSuggestion]:
    """Trailing-3-month median actual per category, rounded to the nearest 5. This is
    the whole "AI sets up your budget" pitch without a model: a median over three named
    months is something the user can recompute by hand, which a model's guess never is.
    Writes nothing — the caller decides which suggestions become budgets via `upsert`.
    """
    month = _first_of_month(month)
    trailing = [_prior_month(month)]
    trailing.append(_prior_month(trailing[-1]))
    trailing.append(_prior_month(trailing[-1]))
    per_month = [_actuals_for_month(db, household_id, m) for m in trailing]

    out: list[BudgetSuggestion] = []
    for cat in _leaf_categories(db, household_id):
        # A month with no transactions in this category is missing data, not a zero —
        # counting it would drag the median toward zero for anything spent less than
        # monthly (an annual insurance premium, a twice-a-year vet visit).
        samples = [m[cat.id] for m in per_month if cat.id in m]
        if not samples:
            continue
        out.append(
            BudgetSuggestion(
                category_id=cat.id,
                category_name=cat.name,
                amount=_round_to_5(median(samples)),
            )
        )
    out.sort(key=lambda s: s.category_name)
    return out


def copy_from(
    db: Session, household_id: uuid.UUID, src_month: date, dst_month: date
) -> int:
    """Copy every budgeted category from `src_month` into `dst_month`. Upserts under the
    hood, so running it twice leaves the same rows rather than erroring the second time.
    """
    src_month = _first_of_month(src_month)
    dst_month = _first_of_month(dst_month)
    items = [
        BudgetItem(category_id=row.category_id, amount=row.amount, rollover=row.rollover)
        for row in list_budgets(db, household_id, src_month)
    ]
    if not items:
        return 0
    upsert(db, household_id, dst_month, items)
    return len(items)
