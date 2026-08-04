"""Monthly budgets: an amount per category per month, with a purely arithmetic read
model layered on top in later tasks — pace and rollover carry, no ML, no LLM.

`month` is always the first of the calendar month; the date column IS the period, so
there is no period-type or period-length concept anywhere in this module.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.budget import Budget
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
