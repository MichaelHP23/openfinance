"""services/forecast.py — the cadence walk (Task 4), discretionary spend (Task 5),
can_i_afford (Task 6), and goal_projection/goals_overview (Task 7).

Task 4's tests below do not create a Budget row and do not import app.services.budgets
— see the STOP section at the top of this plan for why that boundary matters.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.goal import GoalKind
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.services import budgets, forecast, goals
from app.services.categories import ensure_system_categories, system_category_id


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


def test_discretionary_spend_is_the_current_months_uncovered_budget_spread_evenly(db, household, account):
    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    streaming = system_category_id("Bills & Utilities/Streaming")
    today = date(2026, 7, 1)  # July has 31 days

    budgets.upsert(
        db, household.id, today,
        [
            budgets.BudgetItem(groceries, Decimal("310.00")),
            budgets.BudgetItem(streaming, Decimal("15.00")),
        ],
    )

    # A recurring series whose actual charge landed in Streaming — its budget should
    # be treated as already accounted for by the recurring line, not double-counted
    # as discretionary spend too.
    _series(
        db, household, account, cadence=Cadence.monthly,
        next_expected_on=date(2026, 8, 1), typical_amount=Decimal("15.00"), direction=-1,
        label="Streamer",
    )
    db.add(
        Transaction(
            household_id=household.id, account_id=account.id,
            posted_at=datetime(2026, 6, 15, tzinfo=UTC), amount=Decimal("-15.00"),
            merchant_raw="Streamer", category_id=streaming,
        )
    )
    db.commit()

    days = forecast.project(db, household.id, months=1, today=today)
    discretionary_lines = [c for d in days for c in d.contributions if c.startswith("Discretionary")]
    # Only Groceries' 310.00 counts (Streaming is covered), spread over July's 31 days.
    daily = Decimal("310.00") / 31
    assert len(discretionary_lines) == len(days)  # applied every single day
    assert discretionary_lines[0] == f"Discretionary spend -{daily:.2f}"


def test_discretionary_spend_is_zero_with_no_budgets_at_all(db, household, account):
    ensure_system_categories(db)
    days = forecast.project(db, household.id, months=1, today=date(2026, 7, 1))
    assert all(d.contributions == [] for d in days)


def test_can_i_afford_an_amount_that_empties_the_account(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("1200.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    # Emptying the account to exactly zero is not an overdraft — see Global
    # Constraints deviation 4 for why this is >= 0, not > 0.
    assert result.stays_non_negative is True
    assert result.minimum_balance == Decimal("0.00")


def test_can_i_afford_with_a_budget_present_is_cent_exact_not_a_decimal_residue(db, household, account):
    # Regression for the unquantized daily_discretionary bug: 100.00 / 31 is a
    # repeating decimal, so without quantizing to cents the daily subtraction
    # accumulates ~28-digit residue and can push an exact-zero balance to
    # something like -1E-26, flipping stays_non_negative to False. Quantized,
    # daily_discretionary is exactly 3.23 (100.00 / 31 rounds to that), applied
    # once for each of the 32 days from 2026-07-01 through 2026-08-01 inclusive
    # (32 * 3.23 = 103.36) — a hypothetical of 1096.64 should then land the
    # account at exactly 0.00, not a near-zero artifact.
    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    today = date(2026, 7, 1)
    budgets.upsert(db, household.id, today, [budgets.BudgetItem(groceries, Decimal("100.00"))])

    result = forecast.can_i_afford(
        db, household.id, Decimal("1096.64"), date(2026, 7, 5), months=1, today=today
    )
    assert result.stays_non_negative is True
    assert result.minimum_balance == Decimal("0.00")


def test_can_i_afford_raises_for_an_on_date_beyond_the_forecast_horizon(db, household, account):
    with pytest.raises(forecast.OutOfRangeDate):
        forecast.can_i_afford(
            db, household.id, Decimal("100.00"), date(2026, 9, 1), months=1, today=date(2026, 7, 1)
        )


def test_can_i_afford_an_amount_larger_than_the_balance_goes_negative(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("1500.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert result.stays_non_negative is False
    assert result.minimum_balance < 0


def test_can_i_afford_returns_both_a_baseline_and_a_with_amount_series(db, household, account):
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert len(result.baseline) == len(result.with_amount)
    baseline_day5 = next(d for d in result.baseline if d.on == date(2026, 7, 5))
    with_day5 = next(d for d in result.with_amount if d.on == date(2026, 7, 5))
    assert with_day5.projected_balance == baseline_day5.projected_balance - Decimal("100.00")


def test_can_i_afford_reports_impact_on_each_active_goal(db, household, account):
    goal = goals.create(
        db, household.id, name="Vacation", kind=GoalKind.savings,
        target_amount=Decimal("5000.00"), account_ids=[account.id],
    )
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=12, today=date(2026, 7, 1)
    )
    impact = next(g for g in result.goal_impact if g.goal_id == goal.id)
    assert impact.goal_name == "Vacation"


def test_can_i_afford_ignores_archived_goals(db, household, account):
    from app.schemas.goal import GoalUpdate

    goal = goals.create(
        db, household.id, name="Old Goal", kind=GoalKind.savings,
        target_amount=Decimal("100.00"), account_ids=[account.id],
    )
    goals.update(db, household.id, goal.id, GoalUpdate(status="archived"))
    result = forecast.can_i_afford(
        db, household.id, Decimal("100.00"), date(2026, 7, 5), months=1, today=date(2026, 7, 1)
    )
    assert all(g.goal_id != goal.id for g in result.goal_impact)


def test_goal_projection_uses_monthly_funding_when_set(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("200.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1200.00"), monthly_funding=Decimal("500.00"), account_ids=[acct.id],
    )
    projected = forecast.goal_projection(db, household.id, goal.id, today=date(2026, 7, 1))
    # remaining = 1200 - 200 = 1000; at 500/month that's 2 months -> Sep 1.
    assert projected == date(2026, 9, 1)


def test_goal_projection_uses_the_forecast_surplus_when_monthly_funding_is_null(db, household):
    acct = Account(household_id=household.id, type=AccountType.checking, name="Fund Acct", balance=Decimal("0.00"))
    db.add(acct)
    db.commit()
    # A steady 1000.00/month paycheck as the only cash flow gives the forecast a
    # known, checkable surplus rate to project the goal against.
    _series(
        db, household, acct, cadence=Cadence.monthly,
        next_expected_on=date(2026, 7, 1), typical_amount=Decimal("1000.00"), direction=1,
        label="Paycheck",
    )
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("3000.00"), account_ids=[acct.id],
    )
    projected = forecast.goal_projection(db, household.id, goal.id, months=12, today=date(2026, 7, 1))
    assert projected is not None


def test_goal_projection_raises_for_an_unknown_goal(db, household):
    with pytest.raises(forecast.UnknownGoal):
        forecast.goal_projection(db, household.id, uuid.uuid4())


def test_goal_projection_is_today_when_the_target_is_already_met(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("5000.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000.00"), account_ids=[acct.id],
    )
    assert forecast.goal_projection(db, household.id, goal.id, today=date(2026, 7, 1)) == date(2026, 7, 1)


def test_goals_overview_pairs_progress_with_projected_date_for_every_goal(db, household):
    acct = Account(household_id=household.id, type=AccountType.savings, name="Fund Acct", balance=Decimal("500.00"))
    db.add(acct)
    db.commit()
    goal = goals.create(
        db, household.id, name="Fund", kind=GoalKind.savings,
        target_amount=Decimal("1000.00"), monthly_funding=Decimal("250.00"), account_ids=[acct.id],
    )
    overview = forecast.goals_overview(db, household.id, today=date(2026, 7, 1))
    row = next(o for o in overview if o.goal_id == goal.id)
    assert row.progress == Decimal("500.00")
    assert row.projected_date == date(2026, 9, 1)  # remaining 500 / 250 per month = 2 months
