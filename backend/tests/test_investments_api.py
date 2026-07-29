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


def _household(db, name="Investments API Household") -> uuid.UUID:
    h = Household(name=name)
    db.add(h)
    db.commit()
    return h.id


def _account(db, hid, name="Brokerage") -> Account:
    a = Account(household_id=hid, type=AccountType.investment, name=name, balance=Decimal(0))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture
def api(db):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _as(hid: uuid.UUID) -> None:
    """Every subsequent request through `api` is scoped to this household."""
    app.dependency_overrides[require_household] = lambda: hid


def _buy_body(account_id, symbol="VTI", quantity="10", price="100"):
    return {
        "account_id": str(account_id),
        "symbol": symbol,
        "traded_on": "2026-03-01",
        "type": "buy",
        "quantity": quantity,
        "price_per_unit": price,
        "fees": "0",
        "split_ratio": None,
        "currency": "USD",
        "notes": None,
    }


# --- happy path ----------------------------------------------------------------------


def test_create_trade_then_it_shows_up_in_list_and_securities(api, db):
    hid = _household(db)
    acct = _account(db, hid)
    _as(hid)

    r = api.post("/investments/trades", json=_buy_body(acct.id))
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "VTI"
    assert body["account_id"] == str(acct.id)
    assert Decimal(body["quantity"]) == Decimal(10)

    secs = api.get("/investments/securities").json()
    assert [s["symbol"] for s in secs] == ["VTI"]

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 1
    assert trades_out["trades"][0]["symbol"] == "VTI"


def test_holdings_reflects_created_trade_and_manual_price(api, db):
    hid = _household(db)
    acct = _account(db, hid)
    _as(hid)

    api.post("/investments/trades", json=_buy_body(acct.id, quantity="10", price="100"))
    secs = api.get("/investments/securities").json()
    sec_id = secs[0]["id"]

    holdings = api.get("/investments/holdings").json()
    assert len(holdings["holdings"]) == 1
    h = holdings["holdings"][0]
    assert Decimal(h["units"]) == Decimal(10)
    assert h["price"] is None  # unpriced yet
    assert h["market_value"] is None

    price_resp = api.post(
        "/investments/prices",
        json={"security_id": sec_id, "priced_on": "2026-03-15", "close": "120.00"},
    )
    assert price_resp.status_code == 200

    holdings = api.get("/investments/holdings").json()
    h = holdings["holdings"][0]
    assert Decimal(h["price"]) == Decimal("120.00")
    assert Decimal(h["market_value"]) == Decimal("1200.00")


def test_trades_list_supports_filters_and_limit(api, db):
    hid = _household(db)
    acct1 = _account(db, hid, "A")
    acct2 = _account(db, hid, "B")
    _as(hid)

    api.post("/investments/trades", json=_buy_body(acct1.id, symbol="VTI"))
    api.post(
        "/investments/trades",
        json={**_buy_body(acct2.id, symbol="BND"), "traded_on": "2026-06-01"},
    )

    by_account = api.get(f"/investments/trades?account_id={acct1.id}").json()
    assert by_account["total"] == 1
    assert by_account["trades"][0]["symbol"] == "VTI"

    by_date = api.get("/investments/trades?from=2026-05-01").json()
    assert by_date["total"] == 1
    assert by_date["trades"][0]["symbol"] == "BND"

    limited = api.get("/investments/trades?limit=1").json()
    assert len(limited["trades"]) == 1
    assert limited["total"] == 2  # total reports everything, only the page is truncated


def test_delete_trade_removes_it(api, db):
    hid = _household(db)
    acct = _account(db, hid)
    _as(hid)

    created = api.post("/investments/trades", json=_buy_body(acct.id)).json()
    r = api.delete(f"/investments/trades/{created['id']}")
    assert r.status_code == 200

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 0


# --- error paths -----------------------------------------------------------------------


def test_create_trade_with_unknown_account_is_4xx_not_500(api, db):
    hid = _household(db)
    _as(hid)

    r = api.post("/investments/trades", json=_buy_body(uuid.uuid4()))
    assert 400 <= r.status_code < 500
    assert r.status_code != 500


def test_overselling_is_4xx_not_500(api, db):
    hid = _household(db)
    acct = _account(db, hid)
    _as(hid)

    api.post("/investments/trades", json=_buy_body(acct.id, quantity="5", price="10"))
    sell = {
        **_buy_body(acct.id, quantity="6", price="10"),
        "type": "sell",
        "traded_on": "2026-03-02",
    }
    r = api.post("/investments/trades", json=sell)
    assert 400 <= r.status_code < 500
    assert r.status_code != 500

    # the bad sell never landed
    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 1


def test_delete_missing_trade_is_404(api, db):
    hid = _household(db)
    _as(hid)
    r = api.delete(f"/investments/trades/{uuid.uuid4()}")
    assert r.status_code == 404


def test_set_price_for_unknown_security_is_404(api, db):
    hid = _household(db)
    _as(hid)
    r = api.post(
        "/investments/prices",
        json={"security_id": str(uuid.uuid4()), "priced_on": "2026-03-15", "close": "1.00"},
    )
    assert r.status_code == 404


# --- household isolation ----------------------------------------------------------------


def test_cross_household_read_sees_nothing(api, db):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)

    _as(hid_a)
    api.post("/investments/trades", json=_buy_body(acct_a.id))

    _as(hid_b)
    assert api.get("/investments/securities").json() == []
    holdings = api.get("/investments/holdings").json()
    assert holdings["holdings"] == []
    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 0
    assert trades_out["trades"] == []


def test_cross_household_cannot_create_trade_against_anothers_account(api, db):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)

    _as(hid_b)
    r = api.post("/investments/trades", json=_buy_body(acct_a.id))
    assert r.status_code == 404


def test_cross_household_cannot_delete_anothers_trade(api, db):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)

    _as(hid_a)
    created = api.post("/investments/trades", json=_buy_body(acct_a.id)).json()

    _as(hid_b)
    r = api.delete(f"/investments/trades/{created['id']}")
    assert r.status_code == 404

    _as(hid_a)
    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 1  # nothing was removed


def test_cross_household_cannot_set_price_on_anothers_security(api, db):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    acct_a = _account(db, hid_a)

    _as(hid_a)
    api.post("/investments/trades", json=_buy_body(acct_a.id))
    sec_id = api.get("/investments/securities").json()[0]["id"]

    _as(hid_b)
    r = api.post(
        "/investments/prices",
        json={"security_id": sec_id, "priced_on": "2026-03-15", "close": "999.00"},
    )
    assert r.status_code == 404

    _as(hid_a)
    holdings = api.get("/investments/holdings").json()
    assert holdings["holdings"][0]["price"] is None  # the cross-household write never landed


# --- POST /investments/trades/import -------------------------------------------------


def _import(api, csv_text: str):
    return api.post(
        "/investments/trades/import",
        files={"file": ("trades.csv", csv_text.encode(), "text/csv")},
    )


HAPPY_CSV = (
    "Date,Transaction Type,Symbol,Quantity,Price,Fees,Account\n"
    "2026-01-05,Buy,VTI,10,100.00,1.00,Brokerage\n"
    "2026-02-10,Buy,VTI,5,110.00,0,Brokerage\n"
    "2026-03-01,Sell,VTI,3,120.00,0.50,Brokerage\n"
)


def test_import_happy_path_multi_row(api, db):
    hid = _household(db)
    _account(db, hid, "Brokerage")
    _as(hid)

    r = _import(api, HAPPY_CSV)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 3
    assert body["skipped"] == 0
    assert body["errors"] == []

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 3

    holdings = api.get("/investments/holdings").json()
    [h] = holdings["holdings"]
    assert Decimal(h["units"]) == Decimal("12")  # 10 + 5 - 3


def test_reimport_same_file_is_a_no_op(api, db):
    hid = _household(db)
    _account(db, hid, "Brokerage")
    _as(hid)

    _import(api, HAPPY_CSV)
    r = _import(api, HAPPY_CSV)
    body = r.json()
    assert body["imported"] == 0
    assert body["skipped"] == 3
    assert body["errors"] == []

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 3  # no duplicates landed


def test_malformed_row_reports_error_while_good_rows_still_land(api, db):
    hid = _household(db)
    _account(db, hid, "Brokerage")
    _as(hid)

    csv_text = (
        "Date,Transaction Type,Symbol,Quantity,Price,Fees,Account\n"
        "2026-01-05,Buy,VTI,10,100.00,0,Brokerage\n"
        "2026-01-06,Frobnicate,VTI,5,100.00,0,Brokerage\n"
        "2026-01-07,Buy,BND,4,50.00,0,Brokerage\n"
    )
    r = _import(api, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert len(body["errors"]) == 1
    row, reason = body["errors"][0]
    assert row == 2
    assert "type" in reason.lower()

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 2


def test_oversell_row_reports_error_not_500(api, db):
    hid = _household(db)
    _account(db, hid, "Brokerage")
    _as(hid)

    csv_text = (
        "Date,Transaction Type,Symbol,Quantity,Price,Fees,Account\n"
        "2026-01-05,Sell,VTI,3,100.00,0,Brokerage\n"
    )
    r = _import(api, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 0
    assert body["skipped"] == 0
    assert len(body["errors"]) == 1
    row, reason = body["errors"][0]
    assert row == 1

    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 0


def test_import_cross_household_account_is_rejected(api, db):
    hid_a = _household(db, "Household A")
    hid_b = _household(db, "Household B")
    _account(db, hid_a, "Brokerage")  # only exists in household A
    _as(hid_b)

    csv_text = (
        "Date,Transaction Type,Symbol,Quantity,Price,Fees,Account\n"
        "2026-01-05,Buy,VTI,10,100.00,0,Brokerage\n"
    )
    r = _import(api, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 0
    assert len(body["errors"]) == 1
    row, reason = body["errors"][0]
    assert row == 1
    assert "account" in reason.lower()

    # Nothing landed in household B, and household A's trades are untouched.
    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 0
    _as(hid_a)
    trades_out = api.get("/investments/trades").json()
    assert trades_out["total"] == 0
