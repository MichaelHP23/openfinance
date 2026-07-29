"""CSV import for the trade log — spec §8
(docs/superpowers/specs/2026-07-26-investments-trade-log-design.md).

Mirrors `csv_import.py`'s shape — `csv.DictReader` over a `StringIO`, a sha256
`external_id` for idempotency, pre-load existing ids into a set — but needs per-row
error collection on top: a real trade-log export has bad account names, ambiguous
dates, and sells that would overdraw a position, and one bad row must not block the
other few hundred good ones.

Does not touch the ORM to create trades. Symbol resolution and trade creation both go
through `services.trades.create()` (which itself calls `services.securities`), so the
cost-basis replay validation in `portfolio.py` runs on every imported row exactly as it
does for a hand-entered one. `AccountNotInHousehold` and
`portfolio.InsufficientUnitsError` are both `ValueError` subclasses, so one `except
ValueError` per row turns either into a row error instead of a 500 or an aborted
import.
"""

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.account import Account
from app.models.trade import Trade, TradeType
from app.schemas.investment import TradeIn
from app.services import trades as trades_service

# --- column mapping (spec §8.1) -----------------------------------------------------
# Header text -> canonical field name. Matched case-insensitively and trimmed by the
# caller before this dict is consulted.
_HEADER_ALIASES: dict[str, str] = {
    "date": "date",
    "transaction type": "type",
    "type": "type",
    "stock/etf symbol": "symbol",
    "symbol": "symbol",
    "quantity of units": "quantity",
    "quantity": "quantity",
    "amount per unit": "price",
    "price": "price",
    "trading fees": "fees",
    "fees": "fees",
    "investment account": "account",
    "account": "account",
    "split ratio": "split_ratio",
    "currency": "currency",
    # "Total Amount (before trading fees)" and "Investment Category" are deliberately
    # absent — the former is derived and validation-only (not implemented, see the
    # importer's module report), the latter is Phase 2.
}

_TYPE_ALIASES: dict[str, TradeType] = {
    "buy": TradeType.buy,
    "purchase": TradeType.buy,
    "sell": TradeType.sell,
    "sale": TradeType.sell,
    "dividend": TradeType.dividend,
    "div": TradeType.dividend,
    "distribution": TradeType.dividend,
    "interest": TradeType.dividend,
    "split": TradeType.split,
    "stock split": TradeType.split,
}


@dataclass
class TradeImportResult:
    imported: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


def _decimal(raw: str | None) -> Decimal:
    """Survive the spreadsheet: strip `$`, `,`, whitespace; `(123.45)` -> `-123.45`;
    `""`, `"-"`, `"#N/A"` -> 0."""
    if raw is None:
        return Decimal(0)
    s = raw.strip()
    if s in ("", "-", "#N/A"):
        return Decimal(0)
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").strip()
    if s in ("", "-"):
        return Decimal(0)
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"unparseable number {raw!r}") from exc
    return -value if negative else value


def _decode(raw: bytes) -> str:
    """A file that has been through Excel on Windows may be UTF-8-BOM or cp1252.
    `utf-8-sig` also strips the BOM so `csv.DictReader`'s first header key isn't
    `"﻿Date"`."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_headers(fieldnames: list[str]) -> dict[str, str]:
    """Raw header -> canonical field name. Unrecognised columns are dropped."""
    out: dict[str, str] = {}
    for h in fieldnames:
        canon = _HEADER_ALIASES.get(h.strip().lower())
        if canon:
            out[h] = canon
    return out


def _parse_date(raw: str, *, day_first: bool) -> date:
    s = raw.strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    parts = s.replace("/", "-").split("-")
    if len(parts) != 3:
        raise ValueError(f"unparseable date {raw!r}")
    first, second, year = parts
    day, month = (int(first), int(second)) if day_first else (int(second), int(first))
    return date(int(year), month, day)


def _parse_all_dates(rows: list[dict[str, str]], date_header: str | None) -> bool:
    """Whole-file date-order detection (spec §8.1): try US (`MM-DD-YYYY`) first; if any
    row fails, retry the whole file day-first. Never mix interpretations within one
    import — that silently corrupts dates 1-12. Returns whether day-first won."""
    if date_header is None:
        return False
    try:
        for row in rows:
            _parse_date(row.get(date_header, ""), day_first=False)
        return False
    except ValueError:
        pass
    for row in rows:
        _parse_date(row.get(date_header, ""), day_first=True)  # raises if still bad
    return True


def _external_id(
    traded_on: date, type_: TradeType, symbol: str, quantity: Decimal, price: Decimal, account: str
) -> str:
    key = f"{traded_on.isoformat()}|{type_.value}|{symbol}|{quantity}|{price}|{account.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()


def _account_by_name(db: Session, household_id: uuid.UUID, name: str) -> Account | None:
    return db.scalar(
        select(Account).where(
            Account.household_id == household_id,
            func.lower(Account.name) == name.strip().lower(),
        )
    )


def import_csv(db: Session, household_id: uuid.UUID, raw: bytes | str) -> TradeImportResult:
    text = _decode(raw) if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    header_map = _normalize_headers(reader.fieldnames or [])
    rows = list(reader)
    date_header = next((h for h, canon in header_map.items() if canon == "date"), None)

    try:
        day_first = _parse_all_dates(rows, date_header)
    except ValueError as exc:
        raise ValueError(f"Cannot parse dates in file: {exc}") from exc

    existing = set(
        db.scalars(
            select(Trade.external_id).where(
                Trade.household_id == household_id, Trade.external_id.is_not(None)
            )
        )
    )

    result = TradeImportResult()
    account_cache: dict[str, Account | None] = {}

    for i, row in enumerate(rows, start=1):
        try:
            canon = {c: row.get(h, "") for h, c in header_map.items()}

            symbol = (canon.get("symbol") or "").strip().upper()
            if not symbol:
                raise ValueError("missing symbol")

            type_raw = (canon.get("type") or "").strip().lower()
            type_ = _TYPE_ALIASES.get(type_raw)
            if type_ is None:
                raise ValueError(f"unknown transaction type {canon.get('type')!r}")

            traded_on = _parse_date(canon.get("date", ""), day_first=day_first)
            quantity = _decimal(canon.get("quantity"))
            price = _decimal(canon.get("price"))
            fees = _decimal(canon.get("fees"))
            split_raw = canon.get("split_ratio")
            split_ratio = _decimal(split_raw) if split_raw and split_raw.strip() else None
            currency = (canon.get("currency") or "").strip().upper() or settings.base_currency

            account_name = (canon.get("account") or "").strip()
            if not account_name:
                raise ValueError("missing account")
            cache_key = account_name.lower()
            if cache_key not in account_cache:
                account_cache[cache_key] = _account_by_name(db, household_id, account_name)
            account = account_cache[cache_key]
            if account is None:
                raise ValueError(f"unknown account {account_name!r}")

            ext = _external_id(traded_on, type_, symbol, quantity, price, account_name)
            if ext in existing:
                result.skipped += 1
                continue

            trades_service.create(
                db,
                household_id,
                TradeIn(
                    account_id=account.id,
                    symbol=symbol,
                    traded_on=traded_on,
                    type=type_,
                    quantity=quantity,
                    price_per_unit=price,
                    fees=fees,
                    split_ratio=split_ratio,
                    currency=currency,
                    external_id=ext,
                ),
            )
            existing.add(ext)
            result.imported += 1
        except ValueError as exc:
            # Covers a malformed row (bad number/date/type/account) as well as
            # trades_service.AccountNotInHousehold and portfolio.InsufficientUnitsError
            # — both subclass ValueError, so an over-sell row lands here too, as a row
            # error rather than a 500 or an aborted import.
            result.errors.append((i, str(exc)))

    return result
