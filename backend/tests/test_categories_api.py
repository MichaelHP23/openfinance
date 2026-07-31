import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.household import Household
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False


@pytest.fixture
def client(db):
    household = Household(name="Categories Household")
    db.add(household)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_list_returns_system_taxonomy(client, db):
    ensure_system_categories(db)
    res = client.get("/categories")
    assert res.status_code == 200
    names = {c["name"] for c in res.json()}
    assert "Groceries" in names
    assert all(c["is_system"] for c in res.json() if c["name"] == "Groceries")


def test_create_custom_category(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/categories",
        json={"name": "Boat Fuel", "parent_id": str(system_category_id("Transport"))},
    )
    assert res.status_code == 200
    assert res.json()["is_system"] is False


def test_system_category_cannot_be_renamed(client, db):
    ensure_system_categories(db)
    res = client.patch(
        f"/categories/{system_category_id('Food & Drink/Groceries')}",
        json={"name": "Snacks"},
    )
    assert res.status_code == 403


def test_system_category_cannot_be_deleted(client, db):
    ensure_system_categories(db)
    res = client.delete(f"/categories/{system_category_id('Food & Drink/Groceries')}")
    assert res.status_code == 403


def test_unknown_parent_is_rejected_not_a_500(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/categories",
        json={"name": "Orphan", "parent_id": str(uuid.uuid4())},
    )
    assert res.status_code == 422


def test_category_with_children_is_not_deletable(client, db):
    ensure_system_categories(db)
    parent = client.post("/categories", json={"name": "Boats"}).json()
    client.post("/categories", json={"name": "Fuel", "parent_id": parent["id"]})
    assert client.delete(f"/categories/{parent['id']}").status_code == 409


def test_blank_name_is_rejected(client, db):
    assert client.post("/categories", json={"name": "   "}).status_code in (400, 422)


def test_custom_category_can_be_deleted(client, db):
    ensure_system_categories(db)
    created = client.post("/categories", json={"name": "Boat Fuel"}).json()
    assert client.delete(f"/categories/{created['id']}").status_code == 200
    assert created["id"] not in {c["id"] for c in client.get("/categories").json()}
