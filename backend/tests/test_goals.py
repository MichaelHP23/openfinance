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
