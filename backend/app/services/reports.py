"""Aggregation reads over transactions the household already has. No new tables —
every figure here is a group-by over rows P1's categorization and the base
transaction log already produced. `spending` is the query cross-cutting §6 of the
design spec flags as the one query with real growth over a decade of history; it
relies on the `(household_id, category_id, posted_at)` index P1's migration already
added, and this file adds no second one.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.recurring import RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.services.recurring import merchant_key
from app.services.snapshots import net_worth_series

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
        SpendingBucket(
            key=labels[k],
            key_id=ids[k],
            total=totals[k].quantize(Decimal("0.01")),
            count=counts[k],
        )
        for k in totals
    ]
    buckets.sort(key=lambda b: -b.total)
    return buckets


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

    cents = Decimal("0.01")
    out = []
    for i in range(months):
        k = _shift_month(start_month, i).strftime("%Y-%m")
        inc = income.get(k, Decimal(0))
        exp = expense.get(k, Decimal(0))
        # Quantized to cents for the same reason `spending`'s bucket.total is: NUMERIC(19,4)
        # round-trips through the ORM with four decimal places, which would otherwise leak
        # into the JSON body as e.g. "3000.0000" instead of "3000.00".
        out.append(
            MonthFlow(
                month=k,
                income=inc.quantize(cents),
                expense=exp.quantize(cents),
                net=(inc - exp).quantize(cents),
            )
        )
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

    cents = Decimal("0.01")
    biggest_txn_amount = (-biggest_txn.amount).quantize(cents) if biggest_txn else None
    net_worth_delta = _net_worth_delta(db, household_id, year)

    return YearInReview(
        year=year,
        # Quantized to cents before Pydantic serialization: NUMERIC(19,4) round-trips
        # through the ORM as e.g. Decimal("1000.0000"), which would otherwise leak into
        # the JSON body as "1000.0000" instead of "1000.00" (see `spending`'s bucket.total
        # for the same fix, first needed in Task 1).
        total_in=total_in.quantize(cents),
        total_out=total_out.quantize(cents),
        savings_rate=savings_rate,
        biggest_category=biggest_category,
        biggest_category_amount=biggest_category_amount,
        biggest_transaction_merchant=biggest_txn.merchant_raw if biggest_txn else None,
        biggest_transaction_amount=biggest_txn_amount,
        new_subscriptions=new_subs,
        cancelled_subscriptions=cancelled_subs,
        net_worth_delta=net_worth_delta.quantize(cents) if net_worth_delta is not None else None,
    )
