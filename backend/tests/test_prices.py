import uuid
from datetime import date, timezone
from datetime import datetime as dt
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.household import Household
from app.models.security import Security
from app.models.security_price import SecurityPrice
from app.providers.prices import TwelveDataProvider, YahooPriceProvider, get_provider
from app.services import prices


def _ts(y, m, d) -> int:
    return int(dt(y, m, d, tzinfo=timezone.utc).timestamp())


YAHOO_CHART_BODY = {
    "chart": {
        "result": [
            {
                "meta": {"regularMarketPrice": 241.30, "currency": "USD"},
                "timestamp": [_ts(2026, 7, 22), _ts(2026, 7, 23), _ts(2026, 7, 24)],
                "indicators": {
                    "quote": [{"close": [238.10, None, 239.55]}],
                },
            }
        ],
        "error": None,
    }
}

YAHOO_CHART_NO_META_PRICE = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "USD"},
                "timestamp": [_ts(2026, 7, 22), _ts(2026, 7, 23)],
                "indicators": {"quote": [{"close": [100.0, 101.5]}]},
            }
        ],
        "error": None,
    }
}


def yahoo_provider(handler) -> YahooPriceProvider:
    return YahooPriceProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_yahoo_quote_reads_meta_regular_market_price():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=YAHOO_CHART_BODY)

    assert yahoo_provider(handler).quote("VTI") == Decimal("241.3")


def test_yahoo_quote_falls_back_to_last_close_when_meta_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=YAHOO_CHART_NO_META_PRICE)

    assert yahoo_provider(handler).quote("VTI") == Decimal("101.5")


def test_yahoo_quote_returns_none_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    assert yahoo_provider(handler).quote("NOPE") is None


def test_yahoo_history_skips_null_closes_and_filters_since():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=YAHOO_CHART_BODY)

    hist = yahoo_provider(handler).history("VTI", since=date(2026, 7, 23))
    # the None close on 7/23 is dropped; only 7/24 remains >= since
    assert hist == [(date(2026, 7, 24), Decimal("239.55"))]


TWELVE_DATA_BODY = {
    "status": "ok",
    "values": [
        {"datetime": "2026-07-24", "close": "241.30"},
        {"datetime": "2026-07-23", "close": "238.10"},
    ],
}


def twelvedata_provider(handler) -> TwelveDataProvider:
    return TwelveDataProvider(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_twelvedata_quote_reads_latest_close():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TWELVE_DATA_BODY)

    assert twelvedata_provider(handler).quote("VTI") == Decimal("241.30")


def test_twelvedata_history_is_sorted_ascending_and_filtered():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TWELVE_DATA_BODY)

    hist = twelvedata_provider(handler).history("VTI", since=date(2026, 7, 24))
    assert hist == [(date(2026, 7, 24), Decimal("241.30"))]


def test_twelvedata_reports_none_on_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "message": "bad symbol"})

    assert twelvedata_provider(handler).quote("BAD") is None


def test_get_provider_defaults_to_yahoo(monkeypatch):
    monkeypatch.setattr(settings, "twelve_data_api_key", "")
    assert get_provider().name == "yahoo"


def test_get_provider_uses_twelvedata_when_key_set(monkeypatch):
    monkeypatch.setattr(settings, "twelve_data_api_key", "a-key")
    assert get_provider().name == "twelvedata"
    monkeypatch.setattr(settings, "twelve_data_api_key", "")


# --- services/prices.py: refresh, backfill, manual override -----------------------


class FakeProvider:
    name = "fake"

    def __init__(self, quotes: dict[str, Decimal], history_: dict[str, list[tuple[date, Decimal]]] | None = None):
        self._quotes = quotes
        self._history = history_ or {}

    def quote(self, symbol: str) -> Decimal | None:
        return self._quotes.get(symbol)

    def history(self, symbol: str, since: date) -> list[tuple[date, Decimal]]:
        return [(d, c) for d, c in self._history.get(symbol, []) if d >= since]


def _household(db) -> uuid.UUID:
    h = Household(name="Prices Household")
    db.add(h)
    db.commit()
    return h.id


def _security(db, hid, symbol="VTI", is_manual_price=False) -> Security:
    s = Security(household_id=hid, symbol=symbol, currency="USD", is_manual_price=is_manual_price)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_refresh_upserts_a_quote_for_each_non_manual_security(db):
    hid = _household(db)
    sec = _security(db, hid, "VTI")
    provider = FakeProvider({"VTI": Decimal("241.30")})
    result = prices.refresh(db, hid, provider=provider)
    assert result.updated == 1
    assert result.failed == []
    row = db.scalar(select_first_price(db, sec.id))
    assert row.close == Decimal("241.30")
    assert row.source == "fake"


def select_first_price(db, security_id):
    return select(SecurityPrice).where(SecurityPrice.security_id == security_id)


def test_refresh_skips_manual_price_securities(db):
    hid = _household(db)
    _security(db, hid, "PRIVATECO", is_manual_price=True)
    provider = FakeProvider({"PRIVATECO": Decimal("999")})
    result = prices.refresh(db, hid, provider=provider)
    assert result.updated == 0
    assert result.failed == []


def test_refresh_reports_missing_quote_as_failed(db):
    hid = _household(db)
    _security(db, hid, "GHOST")
    provider = FakeProvider({})
    result = prices.refresh(db, hid, provider=provider)
    assert result.updated == 0
    assert result.failed == ["GHOST"]


def test_manual_override_wins_over_a_later_fetch_for_the_same_day(db):
    hid = _household(db)
    sec = _security(db, hid, "VTI")
    today = date(2026, 7, 26)
    prices.set_manual_price(db, sec.id, today, Decimal("500.00"))

    # Exercise the exact upsert path refresh() uses, for the same (security, day).
    prices._upsert(db, sec.id, today, Decimal("241.30"), "fake")
    db.commit()

    row = db.scalar(select_first_price(db, sec.id))
    assert row.close == Decimal("500.00")
    assert row.source == "manual"


def test_backfill_inserts_full_history(db):
    hid = _household(db)
    sec = _security(db, hid, "VTI")
    history = [
        (date(2026, 1, 1), Decimal("200")),
        (date(2026, 1, 2), Decimal("201")),
    ]
    provider = FakeProvider({}, {"VTI": history})
    result = prices.backfill(db, hid, since=date(2026, 1, 1), provider=provider)
    assert result.updated == 1
    rows = list(db.scalars(select_first_price(db, sec.id).order_by(SecurityPrice.priced_on)))
    assert [(r.priced_on, r.close) for r in rows] == history
