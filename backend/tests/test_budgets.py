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


from datetime import UTC, datetime

from app.models.transaction import Transaction


def _spend(db, household, account, category_id, month: date, amount: str, day: int = 15):
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(month.year, month.month, day, tzinfo=UTC),
            amount=Decimal(amount),
            currency="USD",
            merchant_raw="Test Merchant",
            category_id=category_id,
        )
    )
    db.commit()


def test_status_includes_an_unbudgeted_category_with_zero_actual(db, household):
    ensure_system_categories(db)
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    assert rows  # non-empty: the taxonomy alone gives leaf categories to show
    assert all(r.category_name for r in rows)
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.budgeted == Decimal("0")
    assert groceries.actual == Decimal("0")
    assert groceries.remaining == Decimal("0")


def test_status_omits_a_group_category_that_has_leaves(db, household):
    # Every top-level group in the P1 taxonomy has leaves, and CategoryPicker never
    # offers a group-with-leaves as a selectable value — so a group row here would
    # always read zero and only add clutter. Only categories nothing else is a child of
    # (leaves, or a childless top-level custom category) appear.
    ensure_system_categories(db)
    food_and_drink = system_category_id("Food & Drink")
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    assert all(r.category_id != food_and_drink for r in rows)


def test_actual_is_positive_for_money_spent(db, household, account):
    ensure_system_categories(db)
    _spend(db, household, account, GROCERIES, date(2026, 7, 1), "-42.00")
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.actual == Decimal("42.00")


def test_remaining_is_budget_minus_actual(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 7, 1), [budgets.BudgetItem(GROCERIES, Decimal("100.00"))]
    )
    _spend(db, household, account, GROCERIES, date(2026, 7, 1), "-40.00")
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.remaining == Decimal("60.00")


def test_spend_outside_the_month_does_not_count(db, household, account):
    ensure_system_categories(db)
    _spend(db, household, account, GROCERIES, date(2026, 6, 1), "-40.00")
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.actual == Decimal("0")


def test_pace_on_the_first_day_of_a_31_day_month(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 7, 1), [budgets.BudgetItem(GROCERIES, Decimal("100.00"))]
    )
    _spend(db, household, account, GROCERIES, date(2026, 7, 1), "-50.00", day=1)
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 1))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    # Half the budget spent on day 1 of 31 (elapsed fraction 1/31) is way ahead of pace.
    assert groceries.pace == pytest.approx(0.5 / (1 / 31))


def test_pace_on_the_last_day_of_the_month_is_just_the_spend_fraction(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 7, 1), [budgets.BudgetItem(GROCERIES, Decimal("100.00"))]
    )
    _spend(db, household, account, GROCERIES, date(2026, 7, 1), "-80.00", day=31)
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 31))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.pace == pytest.approx(0.8)


def test_pace_for_a_month_already_fully_in_the_past_uses_elapsed_fraction_one(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 5, 1), [budgets.BudgetItem(GROCERIES, Decimal("100.00"))]
    )
    _spend(db, household, account, GROCERIES, date(2026, 5, 1), "-90.00")
    rows = budgets.status(db, household.id, date(2026, 5, 1), today=date(2026, 7, 1))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.pace == pytest.approx(0.9)


def test_pace_is_none_for_a_month_that_has_not_started(db, household):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 9, 1), [budgets.BudgetItem(GROCERIES, Decimal("100.00"))]
    )
    rows = budgets.status(db, household.id, date(2026, 9, 1), today=date(2026, 7, 1))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.pace is None


def test_pace_is_none_for_an_unbudgeted_category(db, household, account):
    ensure_system_categories(db)
    _spend(db, household, account, GROCERIES, date(2026, 7, 1), "-10.00")
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 15))
    groceries = next(r for r in rows if r.category_id == GROCERIES)
    assert groceries.pace is None
