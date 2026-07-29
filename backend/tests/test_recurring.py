"""Coverage for app/services/recurring.py (SP1 detection engine) and app/api/recurring.py.

Determinism: `recurring.detect()` and `recurring.summary()` both call `datetime.now(UTC)`
internally rather than accepting a clock, so there is no injection seam at the call site.
`_freeze()` below monkeypatches the `datetime` name inside the `recurring` module itself
(a subclass whose `.now()` returns a fixed value) so every test controls "today" explicitly
and never depends on the real wall clock. No freezegun/time-machine dependency is installed
(verified), so this is done with plain `monkeypatch` + a `datetime` subclass — no new
dependency added.

KNOWN SPEC-VS-IMPLEMENTATION GAPS (characterized here, not fixed — see the docstring on each
test for detail; both are also called out in the report):

1. Yearly-cadence charges can never survive the full `detect()` pipeline. `LOOKBACK_DAYS`
   (548 days / 18mo) and `MIN_CHARGES` (3, i.e. 2 gaps) are both spec'd values, but for a
   ~365-day cadence, 3 charges span ~730 days — always more than the 548-day query window —
   so the oldest of the 3 is excluded from `detect()`'s transaction query before grouping
   even happens, and only 2 charges (below MIN_CHARGES) ever reach `_build_candidate`. See
   `test_yearly_cadence_is_unreachable_through_detect_end_to_end`.
2. A merchant that appears as both a charge and a refund/income (spec: "different series")
   only ever keeps ONE of the two through `detect()`: the in-memory `candidates` dict in
   `detect()` (services/recurring.py) is keyed by `merchant_key` alone, not
   `(merchant_key, direction)` — same gap exists one level down in the persisted table's
   unique constraint, which the module's own "ponytail" comment already documents as a known,
   accepted limitation. See `test_opposite_sign_series_collapse_to_the_stronger_one`.

Neither is fixed here: #1 needs a real design decision (raise the lookback or special-case
`MIN_CHARGES` per cadence) and #2 needs a migration (widen the unique constraint), so both are
outside "small, obviously correct" per the task's rules.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.schemas.recurring import SeriesUpdate
from app.services import recurring as recurring_service

app.state.limiter.enabled = False


# --- fixtures & helpers --------------------------------------------------------------


def _household(db, name="Recurring Household") -> uuid.UUID:
    h = Household(name=name)
    db.add(h)
    db.commit()
    return h.id


def _account(db, hid, name="Checking") -> Account:
    a = Account(household_id=hid, type=AccountType.checking, name=name, balance=Decimal(0))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _txn(db, hid, account_id, merchant, amount, on: date) -> Transaction:
    t = Transaction(
        household_id=hid,
        account_id=account_id,
        posted_at=datetime.combine(on, datetime.min.time(), tzinfo=UTC),
        amount=Decimal(amount),
        merchant_raw=merchant,
    )
    db.add(t)
    db.commit()
    return t


def _monthly(db, hid, acct, merchant, amounts: list[str], start: date) -> None:
    """`len(amounts)` charges, one per month, calendar-correct (28th-31st safe)."""
    on = start
    for amt in amounts:
        _txn(db, hid, acct.id, merchant, amt, on)
        month = on.month + 1
        year = on.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        import calendar

        day = min(on.day, calendar.monthrange(year, month)[1])
        on = date(year, month, day)


def _freeze(monkeypatch, when: datetime) -> None:
    """Make `datetime.now(...)` inside app.services.recurring return `when`."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return when

    monkeypatch.setattr(recurring_service, "datetime", _Frozen)


def _bare_txn(posted_at: datetime, amount: str, merchant: str = "Test Co") -> Transaction:
    """An unpersisted Transaction for exercising `_build_candidate` directly."""
    return Transaction(
        household_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        posted_at=posted_at,
        amount=Decimal(amount),
        merchant_raw=merchant,
    )


ANCHOR = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)  # hardcoded, never `datetime.now()`


# --- merchant_key ----------------------------------------------------------------------


def test_merchant_key_collapses_store_numbers():
    a = recurring_service.merchant_key("SQ *COFFEE #4471")
    b = recurring_service.merchant_key("SQ *COFFEE #0012")
    assert a == b == "coffee"


def test_merchant_key_strips_prefixes_and_legal_suffixes():
    assert recurring_service.merchant_key("POS DEBIT Netflix.com LLC") == "netflix com"
    assert recurring_service.merchant_key("ACH DEBIT Acme Corp") == "acme"


# --- cadence classification (unit-level, see gap #1 above for why yearly is tested here) ---


@pytest.mark.parametrize(
    "gap_days,expected_cadence",
    [
        (7, Cadence.weekly),
        (14, Cadence.biweekly),
        (30, Cadence.monthly),
        (91, Cadence.quarterly),
        (365, Cadence.yearly),
    ],
)
def test_cadence_classification_by_gap(gap_days, expected_cadence):
    start = datetime(2020, 1, 1, tzinfo=UTC)
    txns = [_bare_txn(start + timedelta(days=gap_days * i), "-50.00") for i in range(4)]
    candidate = recurring_service._build_candidate(txns)
    assert candidate is not None
    assert candidate.cadence == expected_cadence


def test_yearly_cadence_is_unreachable_through_detect_end_to_end(db, monkeypatch):
    """Characterizes gap #1 in the module docstring above: a real annual charge never
    accumulates 3 in-window charges under the current LOOKBACK_DAYS/MIN_CHARGES pair."""
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    for i in range(3):
        _txn(
            db,
            hid,
            acct.id,
            "Annual Prime",
            Decimal("-139.00"),
            ANCHOR.date() - timedelta(days=365 * (2 - i)),
        )
    result = recurring_service.detect(db, hid)
    assert result.detected == 0
    assert recurring_service.list_for(db, hid, status=None) == []


# --- step 3: reject the obvious ---------------------------------------------------------


def test_two_charges_are_not_a_series(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _txn(db, hid, acct.id, "Netflix", Decimal("-15.49"), date(2026, 6, 14))
    _txn(db, hid, acct.id, "Netflix", Decimal("-15.49"), date(2026, 7, 14))
    result = recurring_service.detect(db, hid)
    assert result.detected == 0
    assert recurring_service.list_for(db, hid, status=None) == []


# --- step 4: cadence tightness -----------------------------------------------------------


def test_monthly_fixed_charge_is_detected(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.cadence == Cadence.monthly
    assert row.typical_amount == Decimal("15.49")
    assert row.confidence >= 80


def test_irregular_gaps_are_rejected(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    on = date(2025, 1, 1)
    for gap in [3, 40, 12, 90]:
        on = on + timedelta(days=gap)
        _txn(db, hid, acct.id, "Erratic Co", Decimal("-20.00"), on)
    # plus the very first charge
    _txn(db, hid, acct.id, "Erratic Co", Decimal("-20.00"), date(2025, 1, 1))
    recurring_service.detect(db, hid)
    assert recurring_service.list_for(db, hid, status=None) == []


def test_one_missed_month_still_detects_with_lower_confidence(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    # clean baseline: 6 perfectly monthly charges
    _monthly(db, hid, acct, "Gym Clean", ["-40.00"] * 6, date(2026, 1, 14))
    # a sibling series with a missed month in the middle (gap ~60 days)
    dates = [
        date(2026, 1, 14),
        date(2026, 2, 14),
        date(2026, 4, 15),  # ~60 days after Feb 14
        date(2026, 5, 15),
        date(2026, 6, 15),
        date(2026, 7, 15),
    ]
    for d in dates:
        _txn(db, hid, acct.id, "Gym Shaky", Decimal("-40.00"), d)
    recurring_service.detect(db, hid)
    rows = {r.label: r for r in recurring_service.list_for(db, hid, status=None)}
    assert rows["Gym Shaky"].cadence == Cadence.monthly
    assert recurring_service.MIN_CONFIDENCE <= rows["Gym Shaky"].confidence < rows["Gym Clean"].confidence


# --- step 5: amount stability -------------------------------------------------------------


def test_wildly_varying_amounts_are_rejected(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    amounts = ["-5.00", "-500.00", "-40.00", "-900.00"]
    _monthly(db, hid, acct, "Chaos Inc", amounts, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    assert recurring_service.list_for(db, hid, status=None) == []


def test_variable_bill_is_kept_and_flagged(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    amounts = ["-88.00", "-104.00", "-95.00", "-119.00"]
    _monthly(db, hid, acct, "Electric Co", amounts, date(2026, 4, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.cadence == Cadence.monthly
    assert row.amount_varies is True
    assert row.min_amount == Decimal("88.00")
    assert row.max_amount == Decimal("119.00")


def test_a_shaky_series_is_still_registered_but_at_low_confidence(db, monkeypatch):
    """3 charges (the minimum), variable amounts (0.5 amount_score) — a much shakier
    signal than the fixed-price clean case, but still >= MIN_CONFIDENCE so it registers."""
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    # quarterly-ish, 2 clean gaps, but the amount swings ~40% — spread in the 0.5 bucket
    _txn(db, hid, acct.id, "Variable Quarterly", Decimal("-50.00"), date(2026, 1, 14))
    _txn(db, hid, acct.id, "Variable Quarterly", Decimal("-70.00"), date(2026, 4, 14))
    _txn(db, hid, acct.id, "Variable Quarterly", Decimal("-50.00"), date(2026, 7, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert recurring_service.MIN_CONFIDENCE <= row.confidence < 80


# --- step 7: derived fields ----------------------------------------------------------------


def test_next_expected_clamps_to_month_length(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, datetime(2027, 2, 15, 12, 0, tzinfo=UTC))
    _txn(db, hid, acct.id, "Month End Co", Decimal("-9.00"), date(2026, 11, 30))
    _txn(db, hid, acct.id, "Month End Co", Decimal("-9.00"), date(2026, 12, 31))
    _txn(db, hid, acct.id, "Month End Co", Decimal("-9.00"), date(2027, 1, 31))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.cadence == Cadence.monthly
    # 2027 is not a leap year -> Feb has 28 days, so the 31st clamps to the 28th.
    assert row.next_expected_on == date(2027, 2, 28)


def test_series_that_stopped_is_marked_ended(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    # last charge Jun 14 2026; "today" frozen ~4.5 months later, well past the grace window
    _freeze(monkeypatch, datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    _monthly(db, hid, acct, "Dead Sub", ["-12.00"] * 6, date(2026, 1, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.status == SeriesStatus.ended


def test_price_increase_is_flagged(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    amounts = ["-9.99"] * 5 + ["-12.99"]
    _monthly(db, hid, acct, "Streaming Co", amounts, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.price_increase_amount == Decimal("3.00")


def test_small_price_change_is_not_flagged(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    amounts = ["-9.99"] * 5 + ["-10.19"]
    _monthly(db, hid, acct, "Cheap Co", amounts, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.price_increase_amount is None


# --- direction ---------------------------------------------------------------------------


def test_income_series_is_detected_with_positive_direction(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    on = date(2026, 4, 15)
    for _ in range(5):
        _txn(db, hid, acct.id, "Employer Payroll", Decimal("2000.00"), on)
        on += timedelta(days=14)
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.direction == 1
    assert row.cadence == Cadence.biweekly


def test_group_buckets_by_merchant_and_sign_separately():
    """Direct test of the private `_group` helper: this stage of the pipeline does what
    the spec says (sign is part of series identity). See gap #2 in the module docstring
    for where that guarantee is lost one step later, in `detect()`'s persistence."""
    txns = [
        _bare_txn(datetime(2026, 1, 1, tzinfo=UTC), "-50.00", "Acme"),
        _bare_txn(datetime(2026, 2, 1, tzinfo=UTC), "-50.00", "Acme"),
        _bare_txn(datetime(2026, 1, 15, tzinfo=UTC), "50.00", "Acme"),
        _bare_txn(datetime(2026, 2, 15, tzinfo=UTC), "50.00", "Acme"),
    ]
    groups = recurring_service._group(txns)
    assert set(groups.keys()) == {("acme", -1), ("acme", 1)}
    assert len(groups[("acme", -1)]) == 2
    assert len(groups[("acme", 1)]) == 2


def test_opposite_sign_series_collapse_to_the_stronger_one(db, monkeypatch):
    """Characterizes gap #2 in the module docstring above. The spec (§5.2 step 2) says a
    charge and a refund/income from the same normalized merchant are "different series",
    but detect()'s in-memory `candidates` dict is keyed by merchant_key alone, so only the
    group with more charges survives a given run. Recorded as-is, not fixed (needs a
    migration to widen the unique constraint to include direction)."""
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Acme", ["50.00"] * 3, date(2026, 1, 14))  # income, weaker signal
    _monthly(db, hid, acct, "Acme", ["-50.00"] * 5, date(2026, 1, 20))  # charges, stronger
    recurring_service.detect(db, hid)
    rows = recurring_service.list_for(db, hid, status=None)
    assert len(rows) == 1  # NOT 2, despite the spec's stated intent
    assert rows[0].direction == -1
    assert rows[0].charge_count == 5


# --- idempotency & user-owned fields -------------------------------------------------------


def test_detect_is_idempotent(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    first = recurring_service.list_for(db, hid, status=None)
    assert len(first) == 1
    first_id = first[0].id

    recurring_service.detect(db, hid)
    second = recurring_service.list_for(db, hid, status=None)
    assert len(second) == 1
    assert second[0].id == first_id  # updated in place, not duplicated


def test_detect_updates_existing_row_when_new_charges_appear(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Netflix", ["-15.49"] * 4, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    row_id = row.id
    assert row.charge_count == 4

    _txn(db, hid, acct.id, "Netflix", Decimal("-15.49"), date(2026, 7, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.id == row_id
    assert row.charge_count == 5


def test_detect_preserves_user_label_and_ignored_status(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    recurring_service.update(
        db, hid, row.id, SeriesUpdate(label="Family Netflix", status="ignored")
    )

    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    assert row.label == "Family Netflix"
    assert row.status == SeriesStatus.ignored


def test_user_touched_series_that_stops_detecting_flips_to_ended_not_deleted(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Old Gym", ["-40.00"] * 4, date(2026, 1, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    recurring_service.update(db, hid, row.id, SeriesUpdate(notes="cancelled by hand"))

    # simulate the merchant vanishing from history entirely by re-detecting far later,
    # past the household's transaction window
    _freeze(monkeypatch, ANCHOR + timedelta(days=600))
    recurring_service.detect(db, hid)
    row = recurring_service.get(db, hid, row.id)
    assert row is not None  # not deleted, because it was user-touched (has notes)
    assert row.status == SeriesStatus.ended


def test_untouched_series_that_stops_detecting_is_removed(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid, acct, "Forgotten Sub", ["-12.00"] * 4, date(2026, 1, 14))
    recurring_service.detect(db, hid)
    [row] = recurring_service.list_for(db, hid, status=None)
    row_id = row.id

    _freeze(monkeypatch, ANCHOR + timedelta(days=600))
    recurring_service.detect(db, hid)
    assert recurring_service.get(db, hid, row_id) is None


# --- monthly_committed / summary -----------------------------------------------------------


def test_monthly_committed_normalizes_cadences_without_float_drift():
    series = [
        RecurringSeries(
            household_id=uuid.uuid4(),
            merchant_key="weekly-co",
            label="Weekly Co",
            cadence=Cadence.weekly,
            status=SeriesStatus.active,
            direction=-1,
            typical_amount=Decimal("10.00"),
            last_amount=Decimal("10.00"),
            min_amount=Decimal("10.00"),
            max_amount=Decimal("10.00"),
            charge_count=6,
            first_charged_on=date(2026, 1, 1),
            last_charged_on=date(2026, 7, 1),
        ),
        RecurringSeries(
            household_id=uuid.uuid4(),
            merchant_key="monthly-co",
            label="Monthly Co",
            cadence=Cadence.monthly,
            status=SeriesStatus.active,
            direction=-1,
            typical_amount=Decimal("30.00"),
            last_amount=Decimal("30.00"),
            min_amount=Decimal("30.00"),
            max_amount=Decimal("30.00"),
            charge_count=6,
            first_charged_on=date(2026, 1, 1),
            last_charged_on=date(2026, 7, 1),
        ),
        RecurringSeries(
            household_id=uuid.uuid4(),
            merchant_key="yearly-co",
            label="Yearly Co",
            cadence=Cadence.yearly,
            status=SeriesStatus.active,
            direction=-1,
            typical_amount=Decimal("120.00"),
            last_amount=Decimal("120.00"),
            min_amount=Decimal("120.00"),
            max_amount=Decimal("120.00"),
            charge_count=3,
            first_charged_on=date(2024, 1, 1),
            last_charged_on=date(2026, 1, 1),
        ),
        # an active INCOME series must not bleed into the outgoing total
        RecurringSeries(
            household_id=uuid.uuid4(),
            merchant_key="payroll",
            label="Payroll",
            cadence=Cadence.monthly,
            status=SeriesStatus.active,
            direction=1,
            typical_amount=Decimal("5000.00"),
            last_amount=Decimal("5000.00"),
            min_amount=Decimal("5000.00"),
            max_amount=Decimal("5000.00"),
            charge_count=6,
            first_charged_on=date(2026, 1, 1),
            last_charged_on=date(2026, 7, 1),
        ),
        # ignored/ended series must not be counted even though they're "active" amount-wise
        RecurringSeries(
            household_id=uuid.uuid4(),
            merchant_key="cancelled-co",
            label="Cancelled Co",
            cadence=Cadence.monthly,
            status=SeriesStatus.cancelled,
            direction=-1,
            typical_amount=Decimal("999.00"),
            last_amount=Decimal("999.00"),
            min_amount=Decimal("999.00"),
            max_amount=Decimal("999.00"),
            charge_count=6,
            first_charged_on=date(2026, 1, 1),
            last_charged_on=date(2026, 7, 1),
        ),
    ]
    total = recurring_service.monthly_committed(series, direction=-1)
    expected = (
        Decimal("10.00") * (Decimal(52) / Decimal(12))
        + Decimal("30.00")
        + Decimal("120.00") * (Decimal(1) / Decimal(12))
    ).quantize(Decimal("0.01"))
    assert total == expected
    assert recurring_service.monthly_committed(series, direction=1) == Decimal("5000.00")


def test_summary_reports_upcoming_and_price_increase_counts(db, monkeypatch):
    hid = _household(db)
    acct = _account(db, hid)
    _freeze(monkeypatch, ANCHOR)
    # active, upcoming within 30 days, with a price increase
    _monthly(db, hid, acct, "Streaming Co", ["-9.99"] * 5 + ["-12.99"], date(2026, 2, 14))
    recurring_service.detect(db, hid)
    s = recurring_service.summary(db, hid)
    assert s.active_count == 1
    assert s.price_increases == 1
    assert len(s.upcoming) == 1
    assert s.upcoming[0]["label"] == "Streaming Co"
    assert s.last_detected_at is not None


# --- tenancy (service level) ----------------------------------------------------------------


def test_series_do_not_leak_across_households(db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid_a, acct_a, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid_a)

    assert recurring_service.list_for(db, hid_b, status=None) == []
    recurring_service.detect(db, hid_b)  # must not pick up household A's transactions
    assert recurring_service.list_for(db, hid_b, status=None) == []


def test_get_returns_none_for_another_household(db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid_a, acct_a, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid_a)
    [row] = recurring_service.list_for(db, hid_a, status=None)

    assert recurring_service.get(db, hid_b, row.id) is None


def test_update_is_a_noop_for_another_household(db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid_a, acct_a, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid_a)
    [row] = recurring_service.list_for(db, hid_a, status=None)

    result = recurring_service.update(db, hid_b, row.id, SeriesUpdate(label="Hijacked"))
    assert result is None
    still = recurring_service.get(db, hid_a, row.id)
    assert still.label == "Netflix"


def test_charges_only_returns_the_calling_households_transactions(db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)
    acct_b = _account(db, hid_b)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid_a, acct_a, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    # same merchant name in household B — must never show up in A's charge list
    _monthly(db, hid_b, acct_b, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid_a)
    [row] = recurring_service.list_for(db, hid_a, status=None)

    chgs = recurring_service.charges(db, hid_a, row)
    assert len(chgs) == 6
    assert all(t.household_id == hid_a for t in chgs)


# --- API ---------------------------------------------------------------------------------


@pytest.fixture
def api(db):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _as(hid: uuid.UUID) -> None:
    app.dependency_overrides[require_household] = lambda: hid


def _seed_detected_series(db, hid, monkeypatch, label="Netflix", amounts=None, when=ANCHOR):
    acct = _account(db, hid)
    _freeze(monkeypatch, when)
    _monthly(db, hid, acct, label, amounts or ["-15.49"] * 6, date(2026, 2, 14))
    recurring_service.detect(db, hid)
    return recurring_service.list_for(db, hid, status=None)[0]


def test_api_list_defaults_to_active_and_all_widens_it(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    # last charge Jul 14 2026; detect "today" as Nov 1 2026 so it reads as stopped/ended
    _seed_detected_series(
        db, hid, monkeypatch, "Dead Sub", when=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    active = api.get("/recurring").json()
    assert active == []  # the seeded series already stopped, so "active" (default) hides it

    everything = api.get("/recurring?status=all").json()
    assert len(everything) == 1
    assert everything[0]["label"] == "Dead Sub"


def test_api_list_unknown_status_is_422(api, db):
    hid = _household(db)
    _as(hid)
    r = api.get("/recurring?status=bogus")
    assert r.status_code == 422


def test_api_summary_happy_path(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    _seed_detected_series(db, hid, monkeypatch)
    body = api.get("/recurring/summary").json()
    assert "monthly_committed" in body
    assert "monthly_incoming" in body
    assert "active_count" in body
    assert isinstance(body["upcoming"], list)


def test_api_get_series_includes_charges(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    row = _seed_detected_series(db, hid, monkeypatch)
    body = api.get(f"/recurring/{row.id}").json()
    assert body["label"] == "Netflix"
    assert len(body["charges"]) == 6


def test_api_get_unknown_id_is_404(api, db):
    hid = _household(db)
    _as(hid)
    r = api.get(f"/recurring/{uuid.uuid4()}")
    assert r.status_code == 404


def test_api_patch_renames_and_ignores(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    row = _seed_detected_series(db, hid, monkeypatch)
    r = api.patch(f"/recurring/{row.id}", json={"label": "Family Netflix", "status": "ignored"})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Family Netflix"
    assert body["status"] == "ignored"

    # persisted, not just echoed back
    again = api.get(f"/recurring/{row.id}").json()
    assert again["label"] == "Family Netflix"
    assert again["status"] == "ignored"


def test_api_patch_cancel_url_and_notes_persist(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    row = _seed_detected_series(db, hid, monkeypatch)
    r = api.patch(
        f"/recurring/{row.id}",
        json={
            "status": "cancelled",
            "cancel_url": "https://netflix.com/cancel",
            "notes": "cancelled 2026-07-28",
        },
    )
    assert r.status_code == 200
    body = api.get(f"/recurring/{row.id}").json()
    assert body["status"] == "cancelled"
    assert body["cancel_url"] == "https://netflix.com/cancel"
    assert body["notes"] == "cancelled 2026-07-28"


def test_api_patch_status_ended_is_422(api, db, monkeypatch):
    hid = _household(db)
    _as(hid)
    row = _seed_detected_series(db, hid, monkeypatch)
    r = api.patch(f"/recurring/{row.id}", json={"status": "ended"})
    assert r.status_code == 422


def test_api_patch_unknown_id_is_404(api, db):
    hid = _household(db)
    _as(hid)
    r = api.patch(f"/recurring/{uuid.uuid4()}", json={"label": "x"})
    assert r.status_code == 404


def test_api_refresh_runs_detection_and_returns_counts(api, db):
    hid = _household(db)
    acct = _account(db, hid)
    _as(hid)
    _monthly(db, hid, acct, "Netflix", ["-15.49"] * 5, date(2025, 6, 1))

    r = api.post("/recurring/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["detected"] == 1
    assert body["updated"] == 0
    assert body["removed"] == 0

    # a second refresh updates the existing row rather than detecting a new one
    r2 = api.post("/recurring/refresh")
    body2 = r2.json()
    assert body2["detected"] == 0
    assert body2["updated"] == 1


# --- API tenancy ---------------------------------------------------------------------------


def test_api_list_isolated_by_household(api, db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    _as(hid_a)
    _seed_detected_series(db, hid_a, monkeypatch)

    _as(hid_b)
    assert api.get("/recurring?status=all").json() == []


def test_api_get_another_households_series_is_404_not_leaked(api, db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    _as(hid_a)
    row = _seed_detected_series(db, hid_a, monkeypatch)

    _as(hid_b)
    r = api.get(f"/recurring/{row.id}")
    assert r.status_code == 404  # not 403 — existence isn't confirmed either


def test_api_patch_another_households_series_is_404_and_does_not_mutate(api, db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    _as(hid_a)
    row = _seed_detected_series(db, hid_a, monkeypatch)

    _as(hid_b)
    r = api.patch(f"/recurring/{row.id}", json={"label": "Stolen"})
    assert r.status_code == 404

    _as(hid_a)
    still = api.get(f"/recurring/{row.id}").json()
    assert still["label"] == "Netflix"  # the cross-household write never landed


def test_api_refresh_only_touches_the_calling_household(api, db, monkeypatch):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_b = _account(db, hid_b)
    _freeze(monkeypatch, ANCHOR)
    _monthly(db, hid_b, acct_b, "Netflix", ["-15.49"] * 6, date(2026, 2, 14))

    _as(hid_a)
    r = api.post("/recurring/refresh")
    body = r.json()
    assert body["detected"] == 0  # household A has no transactions of its own

    assert recurring_service.list_for(db, hid_b, status=None) == []  # B untouched by A's refresh
