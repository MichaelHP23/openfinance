import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.trade import TradeType

# Decimal on the wire everywhere — Pydantic serialises Decimal to a JSON string, and
# `money.ts` already accepts `string | number`. No `float` in these schemas.


class SecurityCreate(BaseModel):
    symbol: str
    name: str | None = None
    currency: str = "USD"
    is_manual_price: bool = False


class SecurityUpdate(BaseModel):
    name: str | None = None
    quote_symbol: str | None = None
    is_manual_price: bool | None = None


class SecurityOut(BaseModel):
    id: uuid.UUID
    symbol: str
    name: str | None
    currency: str
    quote_symbol: str | None
    is_manual_price: bool
    model_config = {"from_attributes": True}


class TradeIn(BaseModel):
    # Null only valid for a split — the service fans it out to every account currently
    # holding the security. Every other type requires it.
    account_id: uuid.UUID | None = None
    symbol: str  # resolved to security_id; a new Security is created if unknown
    traded_on: date
    type: TradeType
    quantity: Decimal = Decimal(0)
    price_per_unit: Decimal = Decimal(0)
    # Dividend convenience: total cash when the per-unit rate isn't known. See
    # Trade's docstring — resolved to quantity/price_per_unit at write time.
    amount: Decimal | None = None
    fees: Decimal = Decimal(0)
    split_ratio: Decimal | None = None
    currency: str = "USD"
    notes: str | None = None
    # Set only by the CSV importer (services/trade_import.py) for idempotency —
    # sha256(date|type|symbol|qty|price|account), same shape as csv_import.py's.
    # A hand-entered trade never sets this.
    external_id: str | None = None


class TradeUpdate(BaseModel):
    account_id: uuid.UUID | None = None
    traded_on: date | None = None
    type: TradeType | None = None
    quantity: Decimal | None = None
    price_per_unit: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal | None = None
    split_ratio: Decimal | None = None
    currency: str | None = None
    notes: str | None = None


class TradeOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    security_id: uuid.UUID
    symbol: str
    traded_on: date
    type: TradeType
    quantity: Decimal
    price_per_unit: Decimal
    fees: Decimal
    split_ratio: Decimal | None
    currency: str
    notes: str | None


class TradesOut(BaseModel):
    trades: list[TradeOut]
    total: int


class AccountUnitsOut(BaseModel):
    account_id: uuid.UUID
    name: str
    units: Decimal


class HoldingOut(BaseModel):
    security_id: uuid.UUID
    symbol: str
    name: str | None
    currency: str
    category: str | None = None
    units: Decimal
    avg_cost: Decimal
    cost_base: Decimal
    price: Decimal | None
    priced_on: date | None
    market_value: Decimal | None
    unrealized: Decimal | None
    unrealized_pct: Decimal | None
    dividends: Decimal
    share_pct: Decimal | None
    by_account: list[AccountUnitsOut]


class HoldingsTotals(BaseModel):
    cost_base: Decimal
    market_value: Decimal
    unrealized: Decimal
    dividends: Decimal


class HoldingsOut(BaseModel):
    holdings: list[HoldingOut]
    totals: HoldingsTotals
    priced_through: date | None


class PriceIn(BaseModel):
    security_id: uuid.UUID
    priced_on: date
    close: Decimal


class RefreshOut(BaseModel):
    updated: int
    failed: list[str]


class ImportResultOut(BaseModel):
    imported: int
    skipped: int
    # (1-based row number, reason) tuples — Pydantic serialises a tuple as a 2-element
    # JSON array, matching frontend/src/investments.ts's `TradeImportResult.errors`
    # (`[row: number, reason: string][]`) exactly.
    errors: list[tuple[int, str]]
