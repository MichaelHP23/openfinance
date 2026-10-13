from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.account import Account, AccountType
from app.models.alert_dismissal import AlertDismissal
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.services import alerts
from app.services.alerts import AlertKind

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


def _kinds(found):
    return [a.kind for a in found]


def test_bill_due_fires_within_three_days(db, household, account):
    s = _series(db, household, account, next_expected_on=TODAY + timedelta(days=3))
    found = alerts.list_for(db, household.id, today=TODAY)
    assert _kinds(found) == [AlertKind.bill_due]
    assert found[0].key == f"bill_due:{s.id}:2026-10-15"
    assert found[0].severity == "info"
    assert "Netflix" in found[0].title


def test_bill_due_does_not_fire_four_days_out(db, household, account):
    _series(db, household, account, next_expected_on=TODAY + timedelta(days=4))
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_bill_due_ignores_an_expected_date_already_past(db, household, account):
    _series(db, household, account, next_expected_on=TODAY - timedelta(days=5))
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_bill_due_ignores_income_and_non_active_series(db, household, account):
    soon = TODAY + timedelta(days=1)
    _series(db, household, account, label="Paycheck", direction=1, next_expected_on=soon)
    _series(db, household, account, label="Gym", status=SeriesStatus.ignored, next_expected_on=soon)
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_price_increase_fires_when_flag_is_set(db, household, account):
    s = _series(db, household, account, price_increase_amount=Decimal("3.00"))
    found = alerts.list_for(db, household.id, today=TODAY)
    assert _kinds(found) == [AlertKind.price_increase]
    assert found[0].key == f"price_increase:{s.id}:2026-09-14"
    assert "$3.00" in found[0].body


def test_yearly_renewal_fires_within_thirty_days_and_replaces_bill_due(db, household, account):
    _series(
        db, household, account, label="Domain", cadence=Cadence.yearly,
        next_expected_on=TODAY + timedelta(days=2),
    )
    assert _kinds(alerts.list_for(db, household.id, today=TODAY)) == [AlertKind.yearly_renewal]


def test_yearly_renewal_does_not_fire_thirty_one_days_out(db, household, account):
    _series(
        db, household, account, cadence=Cadence.yearly,
        next_expected_on=TODAY + timedelta(days=31),
    )
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_still_billing_fires_on_a_charge_after_cancellation(db, household, account):
    s = _series(
        db, household, account, status=SeriesStatus.cancelled,
        cancelled_on=date(2026, 9, 20),
    )
    _txn(db, household, account, merchant="Netflix", amount="-15.00", on=date(2026, 10, 14))
    found = alerts.list_for(db, household.id, today=date(2026, 10, 30))
    assert _kinds(found) == [AlertKind.still_billing]
    assert found[0].key == f"still_billing:{s.id}:2026-10-14"
    assert found[0].severity == "urgent"


def test_still_billing_is_quiet_when_the_last_charge_predates_cancellation(db, household, account):
    _series(
        db, household, account, status=SeriesStatus.cancelled,
        cancelled_on=date(2026, 9, 20),
    )
    _txn(db, household, account, merchant="Netflix", amount="-15.00", on=date(2026, 9, 14))
    assert alerts.list_for(db, household.id, today=date(2026, 10, 30)) == []


def test_alerts_sort_urgent_first_then_newest(db, household, account):
    _series(db, household, account, label="Hulu", next_expected_on=TODAY + timedelta(days=1))
    _series(db, household, account, label="Spotify", price_increase_amount=Decimal("2.00"))
    _series(
        db, household, account, label="Netflix", status=SeriesStatus.cancelled,
        cancelled_on=date(2026, 9, 20),
    )
    _txn(db, household, account, merchant="Netflix", amount="-15.00", on=date(2026, 10, 10))
    assert _kinds(alerts.list_for(db, household.id, today=TODAY)) == [
        AlertKind.still_billing, AlertKind.price_increase, AlertKind.bill_due,
    ]
