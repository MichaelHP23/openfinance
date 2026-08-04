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


from app.services import budgets


def test_parse_month_reads_year_dash_month():
    assert budgets.parse_month("2026-07") == date(2026, 7, 1)


def test_parse_month_rejects_garbage():
    with pytest.raises(budgets.BadMonth):
        budgets.parse_month("not-a-month")


def test_parse_month_rejects_a_full_date():
    # The whole point of the path segment is "no day" — the day is always the 1st.
    with pytest.raises(budgets.BadMonth):
        budgets.parse_month("2026-07-15")


def test_upsert_creates_a_row(db, household):
    ensure_system_categories(db)
    rows = budgets.upsert(
        db,
        household.id,
        date(2026, 7, 1),
        [budgets.BudgetItem(category_id=GROCERIES, amount=Decimal("300.00"))],
    )
    assert len(rows) == 1
    assert rows[0].amount == Decimal("300.0000")
    assert rows[0].month == date(2026, 7, 1)
    assert rows[0].rollover is False


def test_upsert_on_an_existing_row_updates_it_in_place(db, household):
    ensure_system_categories(db)
    budgets.upsert(
        db,
        household.id,
        date(2026, 7, 1),
        [budgets.BudgetItem(category_id=GROCERIES, amount=Decimal("300.00"))],
    )
    budgets.upsert(
        db,
        household.id,
        date(2026, 7, 1),
        [budgets.BudgetItem(category_id=GROCERIES, amount=Decimal("350.00"), rollover=True)],
    )
    rows = budgets.list_budgets(db, household.id, date(2026, 7, 1))
    assert len(rows) == 1
    assert rows[0].amount == Decimal("350.0000")
    assert rows[0].rollover is True


def test_upsert_is_idempotent_when_called_with_the_same_values_twice(db, household):
    ensure_system_categories(db)
    item = budgets.BudgetItem(category_id=GROCERIES, amount=Decimal("300.00"))
    budgets.upsert(db, household.id, date(2026, 7, 1), [item])
    budgets.upsert(db, household.id, date(2026, 7, 1), [item])
    assert len(budgets.list_budgets(db, household.id, date(2026, 7, 1))) == 1


def test_upsert_rejects_a_category_the_household_cannot_see(db, household):
    with pytest.raises(budgets.UnknownCategory):
        budgets.upsert(
            db,
            household.id,
            date(2026, 7, 1),
            [budgets.BudgetItem(category_id=uuid.uuid4(), amount=Decimal("10.00"))],
        )


def test_upsert_rejects_another_households_custom_category(db, household):
    from app.schemas.category import CategoryCreate
    from app.services import categories

    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = categories.create(db, other.id, CategoryCreate(name="Their Category"))
    with pytest.raises(budgets.UnknownCategory):
        budgets.upsert(
            db,
            household.id,
            date(2026, 7, 1),
            [budgets.BudgetItem(category_id=theirs.id, amount=Decimal("10.00"))],
        )
