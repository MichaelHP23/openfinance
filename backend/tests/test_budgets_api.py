import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.transaction import Transaction
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False

GROCERIES = system_category_id("Food & Drink/Groceries")


@pytest.fixture
def household(db):
    row = Household(name="Budgets API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Everyday", currency="USD"
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_get_status_returns_every_leaf_category(client, db):
    ensure_system_categories(db)
    res = client.get("/budgets/2026-07")
    assert res.status_code == 200
    names = {r["category_name"] for r in res.json()}
    assert "Groceries" in names


def test_get_status_rejects_a_malformed_month_with_422_not_500(client, db):
    assert client.get("/budgets/not-a-month").status_code == 422


def test_put_upserts_and_a_second_call_is_idempotent(client, db):
    ensure_system_categories(db)
    body = {"items": [{"category_id": str(GROCERIES), "amount": "300.00", "rollover": False}]}
    first = client.put("/budgets/2026-07", json=body)
    assert first.status_code == 200
    assert len(first.json()) == 1

    second = client.put("/budgets/2026-07", json=body)
    assert second.status_code == 200

    status_rows = client.get("/budgets/2026-07").json()
    groceries = next(r for r in status_rows if r["category_id"] == str(GROCERIES))
    assert Decimal(groceries["budgeted"]) == Decimal("300.00")


def test_put_rejects_a_foreign_category_with_422_not_500(client, db):
    body = {"items": [{"category_id": str(uuid.uuid4()), "amount": "10.00"}]}
    res = client.put("/budgets/2026-07", json=body)
    assert res.status_code == 422


def test_suggest_endpoint_returns_medians_and_writes_nothing(client, db, household, account):
    ensure_system_categories(db)
    for iso, amt in [
        ("2026-04-01", "-30.00"),
        ("2026-05-01", "-50.00"),
        ("2026-06-01", "-40.00"),
    ]:
        db.add(
            Transaction(
                household_id=household.id,
                account_id=account.id,
                posted_at=datetime.fromisoformat(iso).replace(tzinfo=UTC),
                amount=Decimal(amt),
                currency="USD",
                merchant_raw="Store",
                category_id=GROCERIES,
            )
        )
    db.commit()

    res = client.post("/budgets/2026-07/suggest")
    assert res.status_code == 200
    groceries = next(s for s in res.json() if s["category_id"] == str(GROCERIES))
    assert Decimal(groceries["amount"]) == Decimal("40")

    status_rows = client.get("/budgets/2026-07").json()
    unbudgeted = next(r for r in status_rows if r["category_id"] == str(GROCERIES))
    assert Decimal(unbudgeted["budgeted"]) == Decimal("0")


def test_copy_endpoint(client, db):
    ensure_system_categories(db)
    client.put(
        "/budgets/2026-06",
        json={"items": [{"category_id": str(GROCERIES), "amount": "300.00"}]},
    )
    res = client.post("/budgets/2026-07/copy", json={"from": "2026-06"})
    assert res.status_code == 200
    assert res.json() == {"copied": 1}

    status_rows = client.get("/budgets/2026-07").json()
    groceries = next(r for r in status_rows if r["category_id"] == str(GROCERIES))
    assert Decimal(groceries["budgeted"]) == Decimal("300.00")
