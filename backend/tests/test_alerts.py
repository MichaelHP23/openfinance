from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.account import Account, AccountType
from app.models.alert_dismissal import AlertDismissal
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.services import alerts, budgets
from app.services.alerts import AlertKind
from app.services.categories import ensure_system_categories, system_category_id

TODAY = date(2026, 10, 12)
GROCERIES = system_category_id("Food & Drink/Groceries")


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
    assert found[0].key == f"price_increase:{s.id}:15.00"
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


def test_low_balance_fires_when_a_bill_takes_cash_below_zero(db, household):
    acct = Account(
        household_id=household.id, type=AccountType.checking, name="Thin",
        currency="USD", balance=Decimal("100.00"),
    )
    db.add(acct)
    db.commit()
    _series(
        db, household, acct, label="Rent", typical_amount=Decimal("900.00"),
        next_expected_on=TODAY + timedelta(days=10),
    )
    found = [a for a in alerts.list_for(db, household.id, today=TODAY) if a.kind == AlertKind.low_balance]
    assert len(found) == 1
    assert found[0].key == "low_balance:cash:2026-10-01"
    assert found[0].severity == "urgent"


def test_low_balance_fires_today_when_cash_is_already_negative(db, household):
    db.add(
        Account(
            household_id=household.id, type=AccountType.checking, name="Overdrawn",
            currency="USD", balance=Decimal("-50.00"),
        )
    )
    db.commit()
    found = alerts.list_for(db, household.id, today=TODAY)
    assert [a.key for a in found] == ["low_balance:cash:2026-10-01"]


def test_low_balance_is_quiet_when_the_dip_is_past_fourteen_days(db, household):
    acct = Account(
        household_id=household.id, type=AccountType.checking, name="Thin",
        currency="USD", balance=Decimal("100.00"),
    )
    db.add(acct)
    db.commit()
    _series(
        db, household, acct, label="Rent", typical_amount=Decimal("900.00"),
        next_expected_on=TODAY + timedelta(days=15),
    )
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_over_budget_fires_when_spend_exceeds_the_budget(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(
        db, household.id, date(2026, 10, 1),
        [budgets.BudgetItem(category_id=GROCERIES, amount=Decimal("300.00"))],
    )
    _txn(db, household, account, merchant="Corner Market", amount="-340.00",
         on=date(2026, 10, 3), category_id=GROCERIES)
    found = [a for a in alerts.list_for(db, household.id, today=TODAY) if a.kind == AlertKind.over_budget]
    assert len(found) == 1
    assert found[0].key == f"over_budget:{GROCERIES}:2026-10-01"
    assert "$40.00" in found[0].body


def test_over_budget_is_quiet_for_spend_in_an_unbudgeted_category(db, household, account):
    ensure_system_categories(db)
    _txn(db, household, account, merchant="Corner Market", amount="-340.00",
         on=date(2026, 10, 3), category_id=GROCERIES)
    assert AlertKind.over_budget not in _kinds(alerts.list_for(db, household.id, today=TODAY))


def test_large_charge_fires_at_three_times_the_usual_amount(db, household, account):
    _series(db, household, account, label="City Power", typical_amount=Decimal("80.00"))
    t = _txn(db, household, account, merchant="City Power", amount="-240.00", on=date(2026, 10, 10))
    found = [a for a in alerts.list_for(db, household.id, today=TODAY) if a.kind == AlertKind.large_charge]
    assert [a.key for a in found] == [f"large_charge:{t.id}:2026-10-10"]


def test_large_charge_fires_at_five_hundred_for_an_unknown_merchant(db, household, account):
    _txn(db, household, account, merchant="Sofa Barn", amount="-500.00", on=date(2026, 10, 10))
    _txn(db, household, account, merchant="Lamp Hut", amount="-499.99", on=date(2026, 10, 10))
    found = [a for a in alerts.list_for(db, household.id, today=TODAY) if a.kind == AlertKind.large_charge]
    assert len(found) == 1
    assert "Sofa Barn" in found[0].title


def test_large_charge_ignores_deposits_and_charges_older_than_a_week(db, household, account):
    _txn(db, household, account, merchant="Employer", amount="3000.00", on=date(2026, 10, 10))
    _txn(db, household, account, merchant="Sofa Barn", amount="-900.00", on=date(2026, 10, 4))
    assert AlertKind.large_charge not in _kinds(alerts.list_for(db, household.id, today=TODAY))


def test_dismissed_alert_is_hidden_and_dismissing_twice_is_fine(db, household, account):
    _series(db, household, account, next_expected_on=TODAY + timedelta(days=1))
    key = alerts.list_for(db, household.id, today=TODAY)[0].key
    alerts.dismiss(db, household.id, key)
    alerts.dismiss(db, household.id, key)
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_dismissal_does_not_hide_the_next_occurrence(db, household, account):
    s = _series(db, household, account, next_expected_on=TODAY + timedelta(days=1))
    alerts.dismiss(db, household.id, alerts.list_for(db, household.id, today=TODAY)[0].key)
    s.next_expected_on = date(2026, 11, 13)
    db.commit()
    assert _kinds(alerts.list_for(db, household.id, today=date(2026, 11, 12))) == [AlertKind.bill_due]


def test_households_do_not_see_or_dismiss_each_others_alerts(db, household, account):
    other = Household(name="Other")
    db.add(other)
    db.commit()
    _series(db, household, account, next_expected_on=TODAY + timedelta(days=1))
    key = alerts.list_for(db, household.id, today=TODAY)[0].key

    assert alerts.list_for(db, other.id, today=TODAY) == []
    alerts.dismiss(db, other.id, key)
    assert [a.key for a in alerts.list_for(db, household.id, today=TODAY)] == [key]


# --- Final review fixes ---------------------------------------------------------------


def test_price_increase_dismissal_survives_the_next_charge_at_the_same_price(db, household, account):
    s = _series(db, household, account, price_increase_amount=Decimal("3.00"))
    alerts.dismiss(db, household.id, alerts.list_for(db, household.id, today=TODAY)[0].key)
    s.last_charged_on = date(2026, 10, 14)
    db.commit()
    assert alerts.list_for(db, household.id, today=date(2026, 10, 15)) == []


def test_price_increase_returns_when_the_price_moves_again(db, household, account):
    s = _series(db, household, account, price_increase_amount=Decimal("3.00"))
    alerts.dismiss(db, household.id, alerts.list_for(db, household.id, today=TODAY)[0].key)
    s.last_amount = Decimal("21.00")
    db.commit()
    assert _kinds(alerts.list_for(db, household.id, today=TODAY)) == [AlertKind.price_increase]


def test_price_increase_ignores_a_pay_rise(db, household, account):
    _series(
        db, household, account, label="Paycheck", direction=1,
        typical_amount=Decimal("2000.00"), price_increase_amount=Decimal("200.00"),
    )
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_large_charge_ignores_transfers_and_card_payments(db, household, account):
    ensure_system_categories(db)
    _txn(db, household, account, merchant="CHASE AUTOPAY", amount="-1800.00", on=date(2026, 10, 10),
         category_id=system_category_id("Transfers/Credit Card Payment"))
    assert alerts.list_for(db, household.id, today=TODAY) == []


def test_low_balance_is_quiet_when_no_cash_account_exists(db, household):
    card = Account(
        household_id=household.id, type=AccountType.credit_card, name="Card",
        currency="USD", balance=Decimal("300.00"),
    )
    db.add(card)
    db.commit()
    _series(db, household, card, next_expected_on=TODAY + timedelta(days=2))
    assert _kinds(alerts.list_for(db, household.id, today=TODAY)) == [AlertKind.bill_due]


def test_low_balance_dismissal_still_holds_the_next_day(db, household):
    db.add(
        Account(
            household_id=household.id, type=AccountType.checking, name="Overdrawn",
            currency="USD", balance=Decimal("-50.00"),
        )
    )
    db.commit()
    alerts.dismiss(db, household.id, alerts.list_for(db, household.id, today=TODAY)[0].key)
    assert alerts.list_for(db, household.id, today=TODAY + timedelta(days=1)) == []
