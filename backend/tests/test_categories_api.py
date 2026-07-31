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
from app.services import categorization
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Categories Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id,
        type=AccountType.checking,
        name="Everyday",
        currency="USD",
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


def _txn(household, account, merchant: str, amount: str = "-42.00") -> Transaction:
    return Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
    )


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


def test_create_rule_and_list_in_priority_order(client, db):
    ensure_system_categories(db)
    groceries = str(system_category_id("Food & Drink/Groceries"))
    coffee = str(system_category_id("Food & Drink/Coffee"))
    client.post(
        "/category-rules",
        json={"pattern": "whole foods", "category_id": groceries, "priority": 50},
    )
    client.post(
        "/category-rules",
        json={"pattern": "blue bottle", "category_id": coffee, "priority": 10},
    )
    rules = client.get("/category-rules").json()
    assert [r["pattern"] for r in rules] == ["blue bottle", "whole foods"]


def test_invalid_regex_is_rejected_with_422(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/category-rules",
        json={
            "match_type": "merchant_regex",
            "pattern": "(unclosed",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert res.status_code == 422
    assert "regular expression" in res.json()["detail"]


def test_rule_pointing_at_a_foreign_category_is_rejected(client, db):
    ensure_system_categories(db)
    res = client.post(
        "/category-rules",
        json={"pattern": "whole foods", "category_id": str(uuid.uuid4())},
    )
    assert res.status_code == 422


def test_reorder_rewrites_priority(client, db):
    ensure_system_categories(db)
    groceries = str(system_category_id("Food & Drink/Groceries"))
    a = client.post(
        "/category-rules", json={"pattern": "aaa", "category_id": groceries}
    ).json()
    b = client.post(
        "/category-rules", json={"pattern": "bbb", "category_id": groceries}
    ).json()
    client.post("/category-rules/reorder", json={"rule_ids": [b["id"], a["id"]]})
    assert [r["pattern"] for r in client.get("/category-rules").json()] == ["bbb", "aaa"]


def test_preview_counts_matches_without_saving(client, db, household, account):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS #4471"))
    db.commit()

    res = client.post(
        "/category-rules/preview",
        json={
            "pattern": "whole foods",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert res.json() == {"matches": 1}
    assert client.get("/category-rules").json() == []


def test_backfill_endpoint_reports_what_changed(client, db, household, account):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS"))
    db.commit()
    client.post(
        "/category-rules",
        json={
            "pattern": "whole foods",
            "category_id": str(system_category_id("Food & Drink/Groceries")),
        },
    )
    assert client.post("/categorization/backfill", json={}).json() == {"changed": 1}


def test_uncategorized_endpoint_rolls_up(client, db, household, account):
    db.add(_txn(household, account, "SHELL OIL #221", "-9.00"))
    db.commit()
    rows = client.get("/categorization/uncategorized").json()
    assert rows[0]["merchant"] == "shell oil"
    assert rows[0]["count"] == 1


def _fake_llm(monkeypatch, reply: str, *, configured: bool = True) -> dict[str, str]:
    """Stand in for ClaudeProvider. Records the prompt so the test can inspect it."""
    seen: dict[str, str] = {}

    def complete(self, system, prompt, max_tokens=1200):
        seen["system"] = system
        seen["prompt"] = prompt
        return reply

    monkeypatch.setattr("app.providers.llm.ClaudeProvider.complete", complete)
    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.configured", property(lambda self: configured)
    )
    return seen


def test_suggest_returns_proposals_and_writes_nothing(
    client, db, household, account, monkeypatch
):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS #4471"))
    db.commit()
    seen = _fake_llm(
        monkeypatch, '[{"merchant": "whole foods", "category": "Food & Drink/Groceries"}]'
    )

    body = client.post("/categories/suggest").json()
    assert body["suggestions"][0]["merchant"] == "whole foods"
    assert body["suggestions"][0]["category_name"] == "Groceries"
    assert categorization.rules_for(db, household.id) == []
    # Only names and the taxonomy leave the machine — no amounts, no dates, no accounts.
    assert "42.00" not in seen["prompt"]
    assert "2026-07-01" not in seen["prompt"]


def test_suggest_is_503_without_an_api_key(client, db, monkeypatch):
    _fake_llm(monkeypatch, "[]", configured=False)
    assert client.post("/categories/suggest").status_code == 503


def test_suggest_drops_a_category_the_model_invented(
    client, db, household, account, monkeypatch
):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS"))
    db.commit()
    _fake_llm(monkeypatch, '[{"merchant": "whole foods", "category": "Nonsense/Invented"}]')
    assert client.post("/categories/suggest").json()["suggestions"] == []


def test_suggest_drops_a_merchant_the_model_invented(
    client, db, household, account, monkeypatch
):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS"))
    db.commit()
    _fake_llm(
        monkeypatch, '[{"merchant": "never asked", "category": "Food & Drink/Groceries"}]'
    )
    assert client.post("/categories/suggest").json()["suggestions"] == []


def test_suggest_survives_a_model_that_does_not_answer_in_json(
    client, db, household, account, monkeypatch
):
    ensure_system_categories(db)
    db.add(_txn(household, account, "WHOLE FOODS"))
    db.commit()
    _fake_llm(monkeypatch, "Sure! Here are my thoughts on groceries.")
    res = client.post("/categories/suggest")
    assert res.status_code == 200
    assert res.json()["suggestions"] == []
