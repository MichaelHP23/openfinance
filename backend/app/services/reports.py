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
