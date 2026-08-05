import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account import Account, AccountType
from app.models.goal import Goal, GoalAccount, GoalKind, GoalStatus
from app.models.household import Household
from app.schemas.goal import GoalUpdate
from app.services import goals


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


def test_create_creates_a_goal_with_no_linked_accounts(db, household):
    row = goals.create(
        db, household.id, name="Emergency Fund", kind=GoalKind.savings,
        target_amount=Decimal("5000.00"),
    )
    assert row.id is not None
    assert goals.linked_account_ids(db, household.id, row.id) == []


def test_create_links_the_given_accounts(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    assert goals.linked_account_ids(db, household.id, row.id) == [account.id]


def test_create_rejects_an_account_the_household_cannot_see(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = Account(household_id=other.id, type=AccountType.checking, name="Theirs")
    db.add(theirs)
    db.commit()
    with pytest.raises(goals.UnknownAccount):
        goals.create(
            db, household.id, name="Fund", kind=GoalKind.savings,
            target_amount=Decimal("100"), account_ids=[theirs.id],
        )


def test_list_for_only_returns_this_households_goals(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    goals.create(db, household.id, name="Mine", kind=GoalKind.savings, target_amount=Decimal("1"))
    goals.create(db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1"))
    assert {g.name for g in goals.list_for(db, household.id)} == {"Mine"}


def test_get_returns_none_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.get(db, household.id, theirs.id) is None


def test_update_changes_fields_and_replaces_linked_accounts(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    other_account = Account(household_id=household.id, type=AccountType.checking, name="Other")
    db.add(other_account)
    db.commit()

    updated = goals.update(
        db, household.id, row.id, GoalUpdate(name="Renamed", account_ids=[other_account.id])
    )
    assert updated.name == "Renamed"
    assert goals.linked_account_ids(db, household.id, row.id) == [other_account.id]


def test_update_rejects_an_unknown_account(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    with pytest.raises(goals.UnknownAccount):
        goals.update(db, household.id, row.id, GoalUpdate(account_ids=[uuid.uuid4()]))


def test_update_returns_none_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.update(db, household.id, theirs.id, GoalUpdate(name="Hijacked")) is None


def test_update_leaves_account_links_alone_when_not_provided(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    goals.update(db, household.id, row.id, GoalUpdate(name="Renamed Only"))
    assert goals.linked_account_ids(db, household.id, row.id) == [account.id]


def test_delete_removes_the_goal_and_its_links(db, household, account):
    row = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("100"), account_ids=[account.id],
    )
    assert goals.delete(db, household.id, row.id) is True
    assert goals.get(db, household.id, row.id) is None


def test_delete_returns_false_for_a_foreign_goal(db, household):
    other = Household(name="Other Household")
    db.add(other)
    db.commit()
    theirs = goals.create(
        db, other.id, name="Theirs", kind=GoalKind.savings, target_amount=Decimal("1")
    )
    assert goals.delete(db, household.id, theirs.id) is False


def test_progress_for_savings_is_the_summed_linked_balance(db, household):
    a1 = Account(household_id=household.id, type=AccountType.savings, name="A1", balance=Decimal("300.00"))
    a2 = Account(household_id=household.id, type=AccountType.checking, name="A2", balance=Decimal("150.00"))
    db.add_all([a1, a2])
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000"), account_ids=[a1.id, a2.id],
    )
    assert goals.progress_for(db, household.id, goal) == Decimal("450.00")


def test_progress_for_debt_payoff_is_the_amount_paid_down_from_target(db, household):
    loan = Account(household_id=household.id, type=AccountType.loan, name="Car Loan", balance=Decimal("-7000.00"))
    db.add(loan)
    db.commit()
    goal = goals.create(
        db, household.id, name="Payoff", kind=GoalKind.debt_payoff,
        target_amount=Decimal("10000.00"), account_ids=[loan.id],
    )
    # target_amount is read as the original 10000.00 owed; 7000.00 remains, so
    # 3000.00 has been paid down.
    assert goals.progress_for(db, household.id, goal) == Decimal("3000.00")


def test_progress_for_debt_payoff_handles_a_positive_stored_balance_too(db, household):
    # Some providers store a liability balance as a positive "amount owed" rather
    # than a negative one — progress_for takes the absolute value either way, the
    # same defensive stance services/snapshots.py already takes for net worth.
    loan = Account(household_id=household.id, type=AccountType.loan, name="Car Loan", balance=Decimal("7000.00"))
    db.add(loan)
    db.commit()
    goal = goals.create(
        db, household.id, name="Payoff", kind=GoalKind.debt_payoff,
        target_amount=Decimal("10000.00"), account_ids=[loan.id],
    )
    assert goals.progress_for(db, household.id, goal) == Decimal("3000.00")


def test_progress_for_a_goal_with_no_linked_accounts_is_zero_for_either_kind(db, household):
    savings_goal = goals.create(db, household.id, name="S", kind=GoalKind.savings, target_amount=Decimal("500"))
    debt_goal = goals.create(db, household.id, name="D", kind=GoalKind.debt_payoff, target_amount=Decimal("500"))
    assert goals.progress_for(db, household.id, savings_goal) == Decimal("0")
    assert goals.progress_for(db, household.id, debt_goal) == Decimal("0")
