from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Alerts API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[require_household] = lambda: household.id
    yield csrf_client(app, db, get_db)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


@pytest.fixture
def due_tomorrow(db, household):
    account = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        currency="USD", balance=Decimal("5000.00"),
    )
    db.add(account)
    db.commit()
    today = datetime.now(UTC).date()
    row = RecurringSeries(
        household_id=household.id, account_id=account.id, merchant_key="netflix",
        label="Netflix", cadence=Cadence.monthly, status=SeriesStatus.active, direction=-1,
        typical_amount=Decimal("15.00"), last_amount=Decimal("15.00"),
        min_amount=Decimal("15.00"), max_amount=Decimal("15.00"), charge_count=3,
        first_charged_on=today - timedelta(days=90), last_charged_on=today - timedelta(days=29),
        next_expected_on=today + timedelta(days=1), confidence=90,
    )
    db.add(row)
    db.commit()
    return row


def test_get_alerts_returns_the_list(client, due_tomorrow):
    res = client.get("/alerts")
    assert res.status_code == 200
    body = res.json()
    assert [a["kind"] for a in body] == ["bill_due"]
    assert set(body[0]) == {"key", "kind", "severity", "title", "body", "href", "occurred_on"}


def test_get_alerts_is_an_empty_list_for_a_new_household(client):
    assert client.get("/alerts").json() == []


def test_dismiss_hides_the_alert(client, due_tomorrow):
    key = client.get("/alerts").json()[0]["key"]
    assert client.post("/alerts/dismiss", json={"key": key}).status_code == 204
    assert client.post("/alerts/dismiss", json={"key": key}).status_code == 204
    assert client.get("/alerts").json() == []


@pytest.mark.parametrize("body", [{}, {"key": ""}, {"key": "x" * 201}])
def test_dismiss_rejects_a_malformed_body(client, body):
    assert client.post("/alerts/dismiss", json=body).status_code == 422
