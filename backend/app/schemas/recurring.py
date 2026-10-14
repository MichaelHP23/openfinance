import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator

from app.models.recurring import Cadence, SeriesStatus
from app.services import cancel_links


class CancelHelpOut(BaseModel):
    url: str
    via: str | None
    steps: str | None


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
    cancelled_on: date | None = None
    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cancel_help(self) -> CancelHelpOut | None:
        """Where to cancel, from the built-in directory. The client prefers the
        user's own cancel_url when there is one."""
        found = cancel_links.lookup(self.label)
        if found is None:
            return None
        return CancelHelpOut(url=found.url, via=found.via, steps=found.steps)


class ChargeOut(BaseModel):
    id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    account_id: uuid.UUID
    # A charge IS a transaction, and the series view renders it with the same row the
    # ledger uses — which now carries a category picker. Without this it always reads
    # "Uncategorized", whatever the row actually is.
    category_id: uuid.UUID | None = None
    ignored: bool = False
    tags: list[str] = []
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

    @field_validator("cancel_url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        # This is rendered as a link the user clicks. Anything but https — above all
        # javascript: and data: — is refused here rather than trusted to the client.
        if v is None:
            return None
        v = v.strip()
        if not v.startswith("https://") or len(v) > 2000 or any(c.isspace() for c in v):
            raise ValueError("cancel_url must be an https:// link")
        return v


class UpcomingOut(BaseModel):
    id: uuid.UUID
    label: str
    on: date
    amount: Decimal  # a magnitude, always positive
    direction: int  # -1 money out, 1 money in


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
