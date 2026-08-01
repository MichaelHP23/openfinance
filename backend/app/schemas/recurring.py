import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.recurring import Cadence, SeriesStatus


class SeriesOut(BaseModel):
    id: uuid.UUID
    label: str
    merchant_key: str
    account_id: uuid.UUID | None
    cadence: Cadence
    status: SeriesStatus
    direction: int
    typical_amount: Decimal
    last_amount: Decimal
    min_amount: Decimal
    max_amount: Decimal
    amount_varies: bool
    price_increase_amount: Decimal | None
    charge_count: int
    first_charged_on: date
    last_charged_on: date
    next_expected_on: date | None
    confidence: int
    cancel_url: str | None
    notes: str | None
    model_config = {"from_attributes": True}


class ChargeOut(BaseModel):
    id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    account_id: uuid.UUID
    # A charge IS a transaction, and the series view renders it with the same row the
    # ledger uses — which now carries a category picker. Without this it always reads
    # "Uncategorized", whatever the row actually is.
    category_id: uuid.UUID | None = None
    model_config = {"from_attributes": True}


class SeriesDetailOut(SeriesOut):
    charges: list[ChargeOut]


class SeriesUpdate(BaseModel):
    label: str | None = None
    # "ended" is detection-owned; a request to set it is a 422, which this Literal
    # produces automatically via pydantic validation.
    status: Literal["active", "cancelled", "ignored"] | None = None
    cancel_url: str | None = None
    notes: str | None = None


class UpcomingOut(BaseModel):
    id: uuid.UUID
    label: str
    on: date
    amount: Decimal


class SummaryOut(BaseModel):
    monthly_committed: Decimal
    monthly_incoming: Decimal
    active_count: int
    upcoming: list[UpcomingOut]
    price_increases: int
    last_detected_at: datetime | None


class DetectionResultOut(BaseModel):
    detected: int
    updated: int
    ended: int
    removed: int
