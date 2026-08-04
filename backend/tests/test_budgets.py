import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.budget import Budget
from app.models.household import Household
from app.services.categories import ensure_system_categories, system_category_id

GROCERIES = system_category_id("Food & Drink/Groceries")


@pytest.fixture
def household(db):
    row = Household(name="Budgets Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id,
        type=AccountType.checking,
        name="Everyday",
        currency="USD",
    )
    db.add(row)
    db.commit()
    return row


def test_budget_row_can_be_created(db, household):
    ensure_system_categories(db)
    row = Budget(
        household_id=household.id,
        category_id=GROCERIES,
        month=date(2026, 7, 1),
        amount=Decimal("300.00"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.id is not None
    assert row.amount == Decimal("300.0000")
    assert row.rollover is False


def test_unique_constraint_rejects_a_second_row_for_the_same_period(db, household):
    ensure_system_categories(db)
    db.add(
        Budget(
            household_id=household.id,
            category_id=GROCERIES,
            month=date(2026, 7, 1),
            amount=Decimal("1.00"),
        )
    )
    db.commit()
    db.add(
        Budget(
            household_id=household.id,
            category_id=GROCERIES,
            month=date(2026, 7, 1),
            amount=Decimal("2.00"),
        )
    )
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_a_different_household_can_budget_the_same_category_and_month(db):
    ensure_system_categories(db)
    h1 = Household(name="H1")
    h2 = Household(name="H2")
    db.add_all([h1, h2])
    db.commit()
    db.add(Budget(household_id=h1.id, category_id=GROCERIES, month=date(2026, 7, 1), amount=Decimal("1.00")))
    db.add(Budget(household_id=h2.id, category_id=GROCERIES, month=date(2026, 7, 1), amount=Decimal("1.00")))
    db.commit()  # must not raise: the unique constraint is scoped per household
