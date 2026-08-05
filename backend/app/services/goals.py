"""Savings and debt-payoff goals.

Progress is always the summed *current* balance of the accounts linked to a goal —
there is no separate contributions ledger. See models/goal.py for why.
"""

import uuid
from datetime import date
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
    target_date: date | None = None,
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
        return Decimal(0)
    balances = list(db.scalars(select(Account.balance).where(Account.id.in_(account_ids))))
    if goal.kind == GoalKind.debt_payoff:
        owed = sum((abs(b) for b in balances), Decimal(0))
        return goal.target_amount - owed
    return sum(balances, Decimal(0))
