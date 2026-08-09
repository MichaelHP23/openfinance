from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.transaction import Transaction
from app.services import reports
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False

GROCERIES = system_category_id("Food & Drink/Groceries")
COFFEE = system_category_id("Food & Drink/Coffee")


@pytest.fixture
def household(db):
    row = Household(name="Reports Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.checking, name="Everyday", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    # For the router-level tests further down — same override pattern every API test
    # file in this plan uses.
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _txn(household, account, amount, merchant, on, category_id=None):
    return Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(on.year, on.month, on.day, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
        category_id=category_id,
    )


def test_spending_groups_by_category(db, household, account):
    ensure_system_categories(db)
    db.add_all(
        [
            _txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 7, 1), GROCERIES),
            _txn(household, account, "-8.00", "TRADER JOE", date(2026, 7, 5), GROCERIES),
            _txn(household, account, "-5.00", "BLUE BOTTLE", date(2026, 7, 2), COFFEE),
            _txn(household, account, "-3.00", "UNKNOWN SHOP", date(2026, 7, 10)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "category")

    assert [b.key for b in buckets] == ["Groceries", "Coffee", "Uncategorized"]
    assert buckets[0].total == Decimal("50.00")
    assert buckets[0].count == 2
    assert buckets[0].key_id == GROCERIES
    assert buckets[2].key_id is None


def test_spending_by_merchant_normalizes_store_numbers(db, household, account):
    db.add_all(
        [
            _txn(household, account, "-10.00", "WHOLE FOODS #1", date(2026, 7, 1)),
            _txn(household, account, "-10.00", "WHOLE FOODS #2", date(2026, 7, 2)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "merchant")

    assert len(buckets) == 1
    assert buckets[0].key == "whole foods"
    assert buckets[0].total == Decimal("20.00")
    assert buckets[0].count == 2


def test_spending_by_month_buckets_on_posted_month(db, household, account):
    db.add_all(
        [
            _txn(household, account, "-10.00", "A", date(2026, 6, 15)),
            _txn(household, account, "-20.00", "B", date(2026, 7, 1)),
        ]
    )
    db.commit()

    buckets = reports.spending(db, household.id, date(2026, 6, 1), date(2026, 7, 31), "month")

    assert [b.key for b in buckets] == ["2026-07", "2026-06"]
    assert buckets[0].total == Decimal("20.00")


def test_spending_ignores_income_rows(db, household, account):
    db.add(_txn(household, account, "100.00", "PAYCHECK", date(2026, 7, 1)))
    db.commit()

    assert reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "category") == []


def test_spending_rejects_unknown_group_by(db, household, account):
    with pytest.raises(reports.BadGroupBy):
        reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "bogus")


def test_spending_endpoint_returns_grouped_buckets(client, db, household, account):
    db.add(_txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 7, 1)))
    db.commit()

    res = client.get("/reports/spending?start=2026-07-01&end=2026-07-31&group_by=merchant")
    assert res.status_code == 200
    body = res.json()
    assert body[0]["key"] == "whole foods"
    assert body[0]["total"] == "42.00"


def test_spending_endpoint_rejects_bad_group_by(client, db):
    res = client.get("/reports/spending?start=2026-07-01&end=2026-07-31&group_by=bogus")
    assert res.status_code == 422


from datetime import UTC as _UTC  # noqa: F401  (already imported above; kept explicit for the diff)

from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.snapshot import BalanceSnapshot


def test_income_vs_expense_covers_every_month_even_empty_ones(db, household, account):
    today = datetime.now(UTC).date()
    current_key = today.replace(day=1).strftime("%Y-%m")
    db.add(_txn(household, account, "3000.00", "PAYCHECK", today.replace(day=1)))
    db.add(_txn(household, account, "-500.00", "RENT", today.replace(day=1)))
    db.commit()

    result = reports.income_vs_expense(db, household.id, months=12)

    assert len(result) == 12
    assert result[-1].month == current_key
    this_month = next(m for m in result if m.month == current_key)
    assert this_month.income == Decimal("3000.00")
    assert this_month.expense == Decimal("500.00")
    assert this_month.net == Decimal("2500.00")
    # A month with no transactions still appears, at zero — a gap in the chart is a
    # real answer ("nothing happened"), not a row that should vanish.
    assert any(m.income == Decimal(0) and m.expense == Decimal(0) for m in result)


def test_year_in_review_computes_expected_fields(db, household, account):
    ensure_system_categories(db)
    electronics = system_category_id("Shopping/Electronics")
    db.add_all(
        [
            _txn(household, account, "3000.00", "PAYCHECK", date(2026, 1, 15)),
            _txn(household, account, "-42.00", "WHOLE FOODS", date(2026, 3, 1), GROCERIES),
            _txn(household, account, "-8.00", "BLUE BOTTLE", date(2026, 3, 2), COFFEE),
            _txn(household, account, "-500.00", "APPLE STORE", date(2026, 5, 1), electronics),
        ]
    )
    db.add(
        RecurringSeries(
            household_id=household.id,
            merchant_key="netflix",
            label="Netflix",
            cadence=Cadence.monthly,
            status=SeriesStatus.active,
            direction=-1,
            typical_amount=Decimal("15.00"),
            last_amount=Decimal("15.00"),
            min_amount=Decimal("15.00"),
            max_amount=Decimal("15.00"),
            charge_count=3,
            first_charged_on=date(2026, 2, 1),
            last_charged_on=date(2026, 4, 1),
            confidence=90,
        )
    )
    db.add(
        RecurringSeries(
            household_id=household.id,
            merchant_key="gym",
            label="Gym",
            cadence=Cadence.monthly,
            status=SeriesStatus.cancelled,
            direction=-1,
            typical_amount=Decimal("40.00"),
            last_amount=Decimal("40.00"),
            min_amount=Decimal("40.00"),
            max_amount=Decimal("40.00"),
            charge_count=3,
            first_charged_on=date(2025, 10, 1),
            last_charged_on=date(2026, 4, 1),
            confidence=90,
        )
    )
    db.commit()

    r = reports.year_in_review(db, household.id, 2026)

    assert r.total_in == Decimal("3000.00")
    assert r.total_out == Decimal("550.00")
    assert r.savings_rate == (Decimal("2450.00") / Decimal("3000.00") * 100)
    assert r.biggest_category == "Electronics"
    assert r.biggest_category_amount == Decimal("500.00")
    assert r.biggest_transaction_merchant == "APPLE STORE"
    assert r.biggest_transaction_amount == Decimal("500.00")
    assert r.new_subscriptions == ["Netflix"]
    assert r.cancelled_subscriptions == ["Gym"]
    assert r.net_worth_delta is None  # no snapshots recorded in this test


def test_year_in_review_net_worth_delta_uses_recorded_snapshots(db, household, account):
    db.add_all(
        [
            BalanceSnapshot(
                household_id=household.id, account_id=account.id,
                captured_on=date(2026, 1, 1), balance=Decimal("1000.00"),
            ),
            BalanceSnapshot(
                household_id=household.id, account_id=account.id,
                captured_on=date(2026, 6, 1), balance=Decimal("1500.00"),
            ),
        ]
    )
    db.commit()

    r = reports.year_in_review(db, household.id, 2026)
    assert r.net_worth_delta == Decimal("500.00")


def test_year_in_review_endpoint(client, db, household, account):
    db.add(Transaction(
        household_id=household.id, account_id=account.id,
        posted_at=datetime(2026, 1, 15, tzinfo=UTC), amount=Decimal("1000.00"),
        currency="USD", merchant_raw="PAYCHECK",
    ))
    db.commit()

    res = client.get("/reports/year-in-review?year=2026")
    assert res.status_code == 200
    assert res.json()["total_in"] == "1000.00"


def test_income_vs_expense_endpoint_default_is_twelve_months(client, db):
    res = client.get("/reports/income-vs-expense")
    assert res.status_code == 200
    assert len(res.json()) == 12
