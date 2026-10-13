from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.account import Account, AccountType
from app.models.alert_dismissal import AlertDismissal
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction

TODAY = date(2026, 10, 12)


@pytest.fixture
def household(db):
    row = Household(name="Alerts Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        currency="USD", balance=Decimal("5000.00"),
    )
    db.add(row)
    db.commit()
    return row


def _series(
    db, household, account, *, label="Netflix", cadence=Cadence.monthly,
    next_expected_on=None, typical_amount=Decimal("15.00"), direction=-1,
    status=SeriesStatus.active, price_increase_amount=None, cancelled_on=None,
    last_charged_on=date(2026, 9, 14),
) -> RecurringSeries:
    row = RecurringSeries(
        household_id=household.id, account_id=account.id, merchant_key=label.lower(),
        label=label, cadence=cadence, status=status, direction=direction,
        typical_amount=typical_amount, last_amount=typical_amount,
        min_amount=typical_amount, max_amount=typical_amount,
        price_increase_amount=price_increase_amount, charge_count=3,
        first_charged_on=date(2026, 7, 14), last_charged_on=last_charged_on,
        next_expected_on=next_expected_on, confidence=90, cancelled_on=cancelled_on,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _txn(db, household, account, *, merchant, amount, on: date, category_id=None) -> Transaction:
    row = Transaction(
        household_id=household.id, account_id=account.id,
        posted_at=datetime(on.year, on.month, on.day, 12, tzinfo=UTC),
        amount=Decimal(amount), merchant_raw=merchant, category_id=category_id,
    )
    db.add(row)
    db.commit()
    return row


def test_dismissal_is_unique_per_household_and_key(db, household):
    db.add(AlertDismissal(household_id=household.id, key="bill_due:x:2026-10-14"))
    db.commit()
    db.add(AlertDismissal(household_id=household.id, key="bill_due:x:2026-10-14"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_series_has_a_nullable_cancelled_on(db, household, account):
    assert _series(db, household, account).cancelled_on is None
