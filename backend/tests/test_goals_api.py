import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Goals API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.savings, name="Fund", balance=Decimal("400.00")
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


def test_create_and_list_goal(client, account):
    res = client.post(
        "/goals",
        json={
            "name": "Emergency Fund", "kind": "savings", "target_amount": "1000.00",
            "account_ids": [str(account.id)],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Emergency Fund"
    assert Decimal(body["progress"]) == Decimal("400.00")

    listed = client.get("/goals").json()
    assert len(listed) == 1


def test_create_rejects_a_foreign_account_with_422_not_500(client):
    res = client.post(
        "/goals",
        json={"name": "Fund", "kind": "savings", "target_amount": "1", "account_ids": [str(uuid.uuid4())]},
    )
    assert res.status_code == 422


def test_patch_updates_fields(client, account):
    created = client.post(
        "/goals",
        json={
            "name": "Fund", "kind": "savings", "target_amount": "1000.00",
            "account_ids": [str(account.id)],
        },
    ).json()
    res = client.patch(f"/goals/{created['id']}", json={"name": "Renamed", "status": "archived"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    assert res.json()["status"] == "archived"


def test_patch_unknown_goal_is_404(client):
    assert client.patch(f"/goals/{uuid.uuid4()}", json={"name": "X"}).status_code == 404


def test_delete_goal(client, account):
    created = client.post(
        "/goals",
        json={"name": "Fund", "kind": "savings", "target_amount": "1", "account_ids": [str(account.id)]},
    ).json()
    assert client.delete(f"/goals/{created['id']}").status_code == 200
    assert client.get("/goals").json() == []


def test_delete_unknown_goal_is_404(client):
    assert client.delete(f"/goals/{uuid.uuid4()}").status_code == 404
