"""services/forecast.py — the cadence walk (Task 4), discretionary spend (Task 5),
can_i_afford (Task 6), and goal_projection/goals_overview (Task 7).

Task 4's tests below do not create a Budget row and do not import app.services.budgets
— see the STOP section at the top of this plan for why that boundary matters.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.services import forecast


@pytest.fixture
def household(db):
    row = Household(name="Forecast Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        currency="USD", balance=Decimal("1200.00"),
    )
    db.add(row)
    db.commit()
    return row


def _series(
    db, household, account, *, cadence, next_expected_on, typical_amount, direction,
    label="Test Series", status=SeriesStatus.active,
) -> RecurringSeries:
    row = RecurringSeries(
        household_id=household.id,
        account_id=account.id,
        merchant_key=label.lower(),
        label=label,
        cadence=cadence,
        status=status,
        direction=direction,
        typical_amount=typical_amount,
        last_amount=typical_amount,
        min_amount=typical_amount,
        max_amount=typical_amount,
        charge_count=3,
        first_charged_on=next_expected_on,
        last_charged_on=next_expected_on,
        next_expected_on=next_expected_on,
        confidence=90,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_forecast_with_zero_recurring_series_is_a_flat_line_at_the_cash_balance(db, household, account):
    days = forecast.project(db, household.id, months=3, today=date(2026, 7, 1))
    assert days
    assert all(d.projected_balance == account.balance for d in days)
    assert all(d.contributions == [] for d in days)


def test_cash_balance_excludes_non_cash_account_types(db, household, account):
    investment = Account(
        household_id=household.id, type=AccountType.investment, name="Brokerage",
        balance=Decimal("50000.00"),
    )
    db.add(investment)
    db.commit()
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    # Only the checking balance counts — the investment mark is not spendable cash.
    assert days[0].projected_balance == Decimal("1200.00")


def test_monthly_cadence_clamps_at_month_end_and_does_not_recover_the_31st(db, household, account):
    # 2026 is not a leap year: Jan 31 -> Feb 28 (clamped) -> Mar 28 (clamped cursor
    # never returns to the 31st once it's dropped to 28 — the same behavior
    # recurring.py's own _add_months already has, deliberately mirrored here).
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 1, 31), typical_amount=Decimal("50.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=3, today=date(2026, 1, 15))
    hits = [d.on for d in days if d.contributions]
    assert hits == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 28)]


def test_monthly_cadence_lands_on_a_real_leap_day(db, household, account):
    # 2028 is a leap year: Jan 31 -> Feb 29 (the actual leap day, not clamped to 28).
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2028, 1, 31), typical_amount=Decimal("50.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=2, today=date(2028, 1, 15))
    hits = [d.on for d in days if d.contributions]
    assert date(2028, 2, 29) in hits


def test_biweekly_cadence_drifts_across_a_calendar_year(db, household, account):
    start = date(2026, 1, 1)
    _series(
        db, household, account, cadence=Cadence.biweekly,
        next_expected_on=start, typical_amount=Decimal("100.00"), direction=1,
    )
    days = forecast.project(db, household.id, months=12, today=start)
    occurrence_days = [d.on for d in days if d.contributions]
    # 14 days doesn't divide the ~365-day span evenly: a year produces 27
    # occurrences, not the 26 a naive 365/14 estimate suggests — that gap is the
    # "drift" the spec's test list names explicitly.
    assert len(occurrence_days) == 27
    assert occurrence_days[0] == start
    assert occurrence_days[-1] == start + timedelta(days=14 * 26)
    assert all((d - start).days % 14 == 0 for d in occurrence_days)


def test_a_series_whose_next_expected_on_is_in_the_past_is_fast_forwarded(db, household, account):
    # Detection can stop running for a while; next_expected_on can be stale by the
    # time a forecast is requested. Walking from the stale date would replay months
    # of phantom missed charges — the walk starts from the first occurrence today
    # or later instead.
    stale = date(2025, 1, 1)
    today = date(2026, 7, 1)
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=stale, typical_amount=Decimal("15.00"), direction=-1,
    )
    days = forecast.project(db, household.id, months=1, today=today)
    occurrence_days = [d.on for d in days if d.contributions]
    assert occurrence_days
    assert occurrence_days[0] >= today
    assert occurrence_days[0].day == 1  # monthly cadence anchored on the 1st


def test_an_ended_series_is_not_walked(db, household, account):
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("15.00"), direction=-1,
        status=SeriesStatus.ended,
    )
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    assert all(d.contributions == [] for d in days)


def test_direction_and_typical_amount_move_the_balance_correctly(db, household, account):
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("1000.00"), direction=1,
        label="Paycheck",
    )
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    payday = next(d for d in days if d.on == date(2026, 7, 1))
    assert payday.projected_balance == Decimal("2200.00")  # 1200 starting + 1000 in
    assert payday.contributions == ["Paycheck +1000.00"]


def test_a_hypothetical_applies_on_its_exact_date_and_nowhere_else(db, household, account):
    hyp = forecast.Hypothetical(amount=Decimal("-500.00"), on_date=date(2026, 7, 10), label="New couch")
    days = forecast.project(db, household.id, months=1, hypotheticals=[hyp], today=date(2026, 7, 1))
    before = next(d for d in days if d.on == date(2026, 7, 9))
    on_day = next(d for d in days if d.on == date(2026, 7, 10))
    after = next(d for d in days if d.on == date(2026, 7, 11))
    assert before.projected_balance == Decimal("1200.00")
    assert on_day.projected_balance == Decimal("700.00")
    assert after.projected_balance == Decimal("700.00")
    assert on_day.contributions == ["New couch -500.00"]
