import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class RealizedGainOut(BaseModel):
    security_id: uuid.UUID
    symbol: str
    account_id: uuid.UUID
    opened_on: date
    closed_on: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    gain: Decimal
    term: str


class RealizedGainsOut(BaseModel):
    year: int
    gains: list[RealizedGainOut]
    short_term_gain: Decimal
    long_term_gain: Decimal
    total_gain: Decimal


class IncomeSummaryOut(BaseModel):
    year: int
    dividends: Decimal
    interest: Decimal
    total: Decimal
