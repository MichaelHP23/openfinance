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
