from datetime import date, timedelta
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
    row = Household(name="Forecast API Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id, type=AccountType.checking, name="Checking",
        balance=Decimal("1000.00"),
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


def test_get_forecast_defaults_to_six_months(client, account):
    res = client.get("/forecast")
    assert res.status_code == 200
    body = res.json()
    assert body
    assert Decimal(body[0]["projected_balance"]) == Decimal("1000.00")


def test_get_forecast_rejects_an_out_of_range_months_with_422_not_500(client, account):
    assert client.get("/forecast?months=0").status_code == 422
    assert client.get("/forecast?months=61").status_code == 422


def test_afford_endpoint_returns_both_series_and_a_verdict(client, account):
    # A few days out from whatever "today" actually is — the route has no `today`
    # override, so a hardcoded historical date would now fall outside the
    # (real-clock) forecast horizon and be rejected as out-of-range.
    soon = (date.today() + timedelta(days=5)).isoformat()
    res = client.post(
        "/forecast/afford", json={"amount": "200.00", "on_date": soon, "months": 1}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stays_non_negative"] is True
    assert len(body["baseline"]) == len(body["with_amount"])


def test_afford_endpoint_rejects_a_non_positive_amount_with_422(client, account):
    res = client.post(
        "/forecast/afford", json={"amount": "0", "on_date": "2026-07-05", "months": 1}
    )
    assert res.status_code == 422


def test_afford_endpoint_rejects_an_on_date_beyond_the_forecast_horizon_with_422(client, account):
    # 400 days out with only a 1-month horizon is beyond range regardless of
    # whatever "today" happens to be when this test runs.
    beyond = (date.today() + timedelta(days=400)).isoformat()
    res = client.post(
        "/forecast/afford", json={"amount": "200.00", "on_date": beyond, "months": 1}
    )
    assert res.status_code == 422
