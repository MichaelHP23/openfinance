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

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Insights API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.checking, name="Checking", balance=Decimal("2000.00"))
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


def _fake_llm(monkeypatch, reply_text: str, *, configured: bool = True):
    def complete_with_tools(self, system, messages, tools, max_tokens=1200):
        from app.providers.llm import ProviderReply

        return ProviderReply(text=reply_text, stop_reason="end_turn")

    monkeypatch.setattr("app.providers.llm.ClaudeProvider.complete_with_tools", complete_with_tools)
    monkeypatch.setattr(
        "app.providers.llm.ClaudeProvider.configured", property(lambda self: configured)
    )


def test_ask_returns_an_answer_a_trace_and_the_model_name(client, db, household, account, monkeypatch):
    db.add(
        Transaction(
            household_id=household.id, account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC), amount=Decimal("-42.00"),
            merchant_raw="Whole Foods",
        )
    )
    db.commit()
    _fake_llm(monkeypatch, "## Where you stand\n- Looking fine.")

    res = client.post("/insights/ask", json={"question": "How am I doing?"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "## Where you stand\n- Looking fine."
    assert body["trace"] == []
    assert body["model"]  # the real ClaudeProvider's configured model name, e.g. "claude-sonnet-5"


def test_ask_accepts_no_body_at_all(client, db, household, account, monkeypatch):
    db.add(
        Transaction(
            household_id=household.id, account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC), amount=Decimal("-42.00"),
            merchant_raw="Whole Foods",
        )
    )
    db.commit()
    _fake_llm(monkeypatch, "## Where you stand\n- Fine.")
    assert client.post("/insights/ask").status_code == 200


def test_ask_is_503_without_an_api_key(client, db, household, account, monkeypatch):
    db.add(
        Transaction(
            household_id=household.id, account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC), amount=Decimal("-42.00"),
            merchant_raw="Whole Foods",
        )
    )
    db.commit()
    _fake_llm(monkeypatch, "unused", configured=False)
    assert client.post("/insights/ask", json={"question": "Anything?"}).status_code == 503


def test_digest_and_available_are_unchanged(client, db):
    assert client.get("/insights/digest").status_code == 200
    assert client.get("/insights/available").json() == {"available": False}


def test_old_post_insights_route_no_longer_exists(client):
    assert client.post("/insights", json={"question": "hi"}).status_code == 404
