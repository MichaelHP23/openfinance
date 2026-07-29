"""Market price providers — Yahoo's unofficial chart endpoint by default, Twelve Data
when a key is configured. Mirrors the shape of `providers/base.py` + `simplefin.py`: a
small protocol, an injectable `httpx.Client` so tests use `MockTransport` and never hit
the network.

See docs/superpowers/specs/2026-07-26-investments-trade-log-design.md §3.

# ponytail: no `yfinance` package. It's a scraper for this exact Yahoo endpoint plus a
# pandas dependency this backend does not have. `httpx` (already a dependency) does the
# same GET directly.
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from app.core.config import settings

TIMEOUT = 30.0
log = logging.getLogger("openfinance.prices")


class PriceProvider(Protocol):
    name: str

    def quote(self, symbol: str) -> Decimal | None: ...
    def history(self, symbol: str, since: date) -> list[tuple[date, Decimal]]: ...


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


class YahooPriceProvider:
    """The unofficial Yahoo Finance chart endpoint. No key, no signup, no SLA.

    Verified live 2026-07-26 against AAPL, ^GSPC, and CADUSD=X with no key and a
    browser-ish User-Agent. It has no terms permitting programmatic use and has broken
    before without notice (2017 shutdown, 2023 cookie/crumb requirement) — an acceptable
    risk for ~20 symbols fetched once a day, with a cheap recovery path: set
    TWELVE_DATA_API_KEY to switch providers.
    """

    name = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injectable so tests drive it with a MockTransport instead of the network.
        self._client = client or httpx.Client(
            timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; openfinance/1.0)"},
        )

    def _chart(self, symbol: str, range_: str) -> dict[str, Any] | None:
        resp = self._client.get(
            f"{self.BASE}/{symbol}", params={"range": range_, "interval": "1d"}
        )
        if resp.status_code != 200:
            log.warning("yahoo returned %s for %s", resp.status_code, symbol)
            return None
        try:
            data = resp.json()
        except ValueError:
            log.warning("yahoo returned non-JSON for %s", symbol)
            return None
        results = (data.get("chart") or {}).get("result") or []
        return results[0] if results else None

    @staticmethod
    def _series(result: dict[str, Any]) -> list[tuple[date, Decimal]]:
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        out: list[tuple[date, Decimal]] = []
        for ts, close in zip(timestamps, closes):
            price = _decimal(close)
            if price is None:
                continue
            out.append((datetime.fromtimestamp(ts, UTC).date(), price))
        return out

    def quote(self, symbol: str) -> Decimal | None:
        result = self._chart(symbol, "5d")
        if result is None:
            return None
        price = _decimal((result.get("meta") or {}).get("regularMarketPrice"))
        if price is not None:
            return price
        closes = self._series(result)
        return closes[-1][1] if closes else None

    def history(self, symbol: str, since: date) -> list[tuple[date, Decimal]]:
        result = self._chart(symbol, "10y")
        if result is None:
            return []
        return [(d, c) for d, c in self._series(result) if d >= since]


class TwelveDataProvider:
    """Keyed provider, used when `TWELVE_DATA_API_KEY` is set. Terms permit this use.

    Free tier as advertised July 2026: 800 credits/day, 8 requests/minute, 5,000 data
    points per request — re-check at deploy time, vendor free tiers move silently.
    """

    name = "twelvedata"
    BASE = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def _series(self, symbol: str, outputsize: int) -> list[tuple[date, Decimal]]:
        resp = self._client.get(
            self.BASE,
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": outputsize,
                "apikey": self._api_key,
            },
        )
        if resp.status_code != 200:
            log.warning("twelvedata returned %s for %s", resp.status_code, symbol)
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        if data.get("status") == "error":
            log.warning("twelvedata error for %s: %s", symbol, data.get("message"))
            return []
        out: list[tuple[date, Decimal]] = []
        for row in data.get("values") or []:
            try:
                d = datetime.strptime(str(row["datetime"])[:10], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            price = _decimal(row.get("close"))
            if price is None:
                continue
            out.append((d, price))
        out.sort(key=lambda r: r[0])
        return out

    def quote(self, symbol: str) -> Decimal | None:
        series = self._series(symbol, outputsize=1)
        return series[-1][1] if series else None

    def history(self, symbol: str, since: date) -> list[tuple[date, Decimal]]:
        # ponytail: fixed outputsize instead of computing days-since-`since`. 5000 daily
        # points is ~19 years, comfortably covers the spec's 10-year backfill. Revisit
        # with a computed size if a household needs more.
        series = self._series(symbol, outputsize=5000)
        return [(d, c) for d, c in series if d >= since]


def get_provider(client: httpx.Client | None = None) -> PriceProvider:
    """Twelve Data when a key is configured, Yahoo otherwise. No key -> no signup."""
    if settings.twelve_data_api_key:
        return TwelveDataProvider(settings.twelve_data_api_key, client=client)
    return YahooPriceProvider(client=client)
