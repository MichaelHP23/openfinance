"""Cash-flow forecast: a daily walk from today's cash balances, applying recurring
cadences, budgeted discretionary spend, and any hypothetical the caller adds. Every
number traces to something real — a recurring series, a budget row, a hypothetical
typed in by hand — never a model's guess. No strategy engine, no simulation: the cut
list (avalanche/snowball, Monte Carlo, retirement projection) stays cut here.
"""

import math
import uuid
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.goal import Goal, GoalStatus
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.services import budgets, goals, recurring

# Balances a household can actually spend from. Net worth (services/snapshots.py,
# already shipped) already answers "what's my whole balance sheet" — this answers
# the narrower "how much spendable cash will I have," so investment/crypto marks and
# every liability/asset type are excluded on purpose. See Global Constraints
# deviation 6.
CASH_ACCOUNT_TYPES = {AccountType.checking, AccountType.savings, AccountType.cash}

_CADENCE_STEP_DAYS = {Cadence.weekly: 7, Cadence.biweekly: 14}
_CADENCE_STEP_MONTHS = {Cadence.monthly: 1, Cadence.quarterly: 3, Cadence.yearly: 12}


def _add_months(d: date, months: int) -> date:
    """Deliberately duplicates recurring.py's own private `_add_months` rather than
    importing a leading-underscore name across modules — same clamping logic (the
    31st in a 30-day month becomes the 30th, and once a cursor clamps it never
    un-clamps), proven already by recurring.py's own detection tests."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _step_forward(d: date, cadence: Cadence) -> date:
    step_days = _CADENCE_STEP_DAYS.get(cadence)
    if step_days is not None:
        return d + timedelta(days=step_days)
    return _add_months(d, _CADENCE_STEP_MONTHS[cadence])


def _first_occurrence_on_or_after(series: RecurringSeries, today: date) -> date | None:
    """A series' next_expected_on can be in the past — nothing rewinds it once
    detection stops running. Fast-forward to the first occurrence today or later
    before the walk starts, rather than replaying every missed occurrence."""
    if series.next_expected_on is None:
        return None
    cursor = series.next_expected_on
    guard = 0
    while cursor < today:
        cursor = _step_forward(cursor, series.cadence)
        guard += 1
        if guard > 10_000:  # a corrupt row; never loop forever over bad data
            return None
    return cursor


def _cash_balance(db: Session, household_id: uuid.UUID) -> Decimal:
    rows = db.scalars(
        select(Account.balance).where(
            Account.household_id == household_id, Account.type.in_(CASH_ACCOUNT_TYPES)
        )
    )
    return sum(rows, Decimal(0))


def _recurring_covered_categories(db: Session, household_id: uuid.UUID) -> set[uuid.UUID]:
    """Category ids already accounted for by an active recurring series, so this
    doesn't double-count a subscription as both a recurring line and discretionary
    spend. RecurringSeries carries no category of its own, so this is built from the
    transactions each series already matches — exactly as expensive as
    recurring.charges() already is anywhere else it's called."""
    covered: set[uuid.UUID] = set()
    for series in recurring.list_for(db, household_id, status=SeriesStatus.active):
        for txn in recurring.charges(db, household_id, series):
            if txn.category_id is not None:
                covered.add(txn.category_id)
    return covered


@dataclass
class Hypothetical:
    amount: Decimal  # negative for an outflow, positive for an inflow
    on_date: date
    label: str = "Hypothetical"


@dataclass
class ForecastDay:
    on: date
    projected_balance: Decimal
    contributions: list[str] = field(default_factory=list)


def project(
    db: Session,
    household_id: uuid.UUID,
    months: int,
    hypotheticals: list[Hypothetical] | None = None,
    *,
    today: date | None = None,
) -> list[ForecastDay]:
    """A daily balance series from today's cash balances through `months` months out.

    1. Starts at today's summed cash-account balances.
    2. Walks forward day by day, applying every active RecurringSeries whose cadence
       lands on that day.
    3. Spreads the current month's budgeted-but-not-recurring-covered spend evenly
       across every day of the horizon (see `_recurring_covered_categories`).
    4. Applies any hypothetical outflows/inflows on their exact date.
    5. Every day's `contributions` names what moved it, so any point on the
       resulting chart is explainable back to a real row.
    """
    today = today or datetime.now(UTC).date()
    end = _add_months(today, months)
    hypotheticals = hypotheticals or []

    balance = _cash_balance(db, household_id)
    active_series = recurring.list_for(db, household_id, status=SeriesStatus.active)
    cursors = {
        s.id: _first_occurrence_on_or_after(s, today)
        for s in active_series
        if s.next_expected_on is not None
    }

    # The current month's budgeted total for categories no recurring series already
    # covers, spread over that month's day count — held constant for the whole
    # horizon. See Global Constraints deviation 5 for why this isn't recomputed
    # per future calendar month.
    covered = _recurring_covered_categories(db, household_id)
    month_start = today.replace(day=1)
    days_in_month = monthrange(today.year, today.month)[1]
    discretionary_total = sum(
        (
            row.budgeted
            for row in budgets.status(db, household_id, month_start)
            if row.category_id not in covered
        ),
        Decimal(0),
    )
    daily_discretionary = (
        discretionary_total / days_in_month if discretionary_total else Decimal(0)
    )

    by_date: dict[date, list[Hypothetical]] = {}
    for h in hypotheticals:
        by_date.setdefault(h.on_date, []).append(h)

    out: list[ForecastDay] = []
    d = today
    while d <= end:
        contributions: list[str] = []

        for s in active_series:
            cursor = cursors.get(s.id)
            if cursor is None:
                continue
            while cursor == d:
                signed = s.typical_amount * s.direction
                balance += signed
                contributions.append(f"{s.label} {signed:+.2f}")
                cursor = _step_forward(cursor, s.cadence)
                cursors[s.id] = cursor

        if daily_discretionary:
            balance -= daily_discretionary
            contributions.append(f"Discretionary spend -{daily_discretionary:.2f}")

        for h in by_date.get(d, []):
            balance += h.amount
            contributions.append(f"{h.label} {h.amount:+.2f}")

        out.append(ForecastDay(on=d, projected_balance=balance, contributions=contributions))
        d += timedelta(days=1)

    return out


def _goal_date_from_series(
    db: Session,
    household_id: uuid.UUID,
    goal: Goal,
    series: list[ForecastDay],
    today: date,
) -> date | None:
    """The date `goal` is reached, given a computed forecast `series` for the
    "use the forecast's surplus" case, or a fixed monthly_funding rate for the case
    the user typed one in by hand. Shared by can_i_afford (comparing baseline vs.
    with-amount) and goal_projection (Task 7)."""
    progress = goals.progress_for(db, household_id, goal)
    remaining = goal.target_amount - progress
    if remaining <= 0:
        return today  # already met

    if goal.monthly_funding:
        # A funding rate the user typed in is a monthly commitment, not a slice of
        # the household's whole cash flow — walk in fixed monthly increments rather
        # than the daily series.
        cursor = today
        remaining_after = remaining
        guard = 0
        while remaining_after > 0:
            cursor = _add_months(cursor, 1)
            remaining_after -= goal.monthly_funding
            guard += 1
            if guard > 1200:  # 100 years; a funding rate too small to ever finish
                return None
        return cursor

    if len(series) < 2:
        return None
    delta = series[-1].projected_balance - series[0].projected_balance
    if delta <= 0:
        return None
    total_days = (series[-1].on - series[0].on).days
    daily_rate = delta / Decimal(total_days)
    days_needed = remaining / daily_rate
    return today + timedelta(days=math.ceil(days_needed))


@dataclass
class GoalAffordability:
    goal_id: uuid.UUID
    goal_name: str
    baseline_date: date | None
    with_amount_date: date | None


@dataclass
class AffordabilityResult:
    baseline: list[ForecastDay]
    with_amount: list[ForecastDay]
    stays_non_negative: bool
    minimum_balance: Decimal
    goal_impact: list[GoalAffordability]


def can_i_afford(
    db: Session,
    household_id: uuid.UUID,
    amount: Decimal,
    on_date: date,
    months: int,
    *,
    today: date | None = None,
) -> AffordabilityResult:
    """Runs project() twice — with and without the hypothetical outflow — so every
    number on the "can I afford this" screen traces to the same walk the forecast
    chart already draws, rather than a separate estimate."""
    today = today or datetime.now(UTC).date()
    baseline = project(db, household_id, months, today=today)
    outflow = Hypothetical(amount=-abs(amount), on_date=on_date, label="Hypothetical purchase")
    with_amount = project(db, household_id, months, [outflow], today=today)

    minimum_balance = min(
        (day.projected_balance for day in with_amount), default=Decimal(0)
    )
    stays_non_negative = minimum_balance >= 0

    goal_impact = [
        GoalAffordability(
            goal_id=g.id,
            goal_name=g.name,
            baseline_date=_goal_date_from_series(db, household_id, g, baseline, today),
            with_amount_date=_goal_date_from_series(db, household_id, g, with_amount, today),
        )
        for g in goals.list_for(db, household_id)
        if g.status == GoalStatus.active
    ]

    return AffordabilityResult(
        baseline=baseline,
        with_amount=with_amount,
        stays_non_negative=stays_non_negative,
        minimum_balance=minimum_balance,
        goal_impact=goal_impact,
    )


class UnknownGoal(Exception):
    """The requested goal does not exist, or belongs to another household."""


def goal_projection(
    db: Session,
    household_id: uuid.UUID,
    goal_id: uuid.UUID,
    *,
    months: int = 12,
    today: date | None = None,
) -> date | None:
    """The date `goal_id` is reached at current funding — the forecast's own
    surplus when monthly_funding is null, per the spec."""
    goal = goals.get(db, household_id, goal_id)
    if goal is None:
        raise UnknownGoal(str(goal_id))
    today = today or datetime.now(UTC).date()
    series = project(db, household_id, months, today=today)
    return _goal_date_from_series(db, household_id, goal, series, today)


@dataclass
class GoalOverview:
    goal_id: uuid.UUID
    progress: Decimal
    projected_date: date | None


def goals_overview(
    db: Session, household_id: uuid.UUID, *, months: int = 12, today: date | None = None
) -> list[GoalOverview]:
    """Progress and a projected completion date for every goal, computed from one
    shared project() call rather than one per goal — the walk is identical
    regardless of which goal is asking."""
    today = today or datetime.now(UTC).date()
    series = project(db, household_id, months, today=today)
    return [
        GoalOverview(
            goal_id=g.id,
            progress=goals.progress_for(db, household_id, g),
            projected_date=_goal_date_from_series(db, household_id, g, series, today),
        )
        for g in goals.list_for(db, household_id)
    ]
