import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class TxnCreate(BaseModel):
    account_id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    merchant_raw: str
    currency: str = "USD"
    category_id: uuid.UUID | None = None
    notes: str | None = None


class TxnUpdate(BaseModel):
    merchant_normalized: str | None = None
    category_id: uuid.UUID | None = None
    notes: str | None = None


class TxnOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    posted_at: datetime
    amount: Decimal
    currency: str
    merchant_raw: str
    merchant_normalized: str | None
    category_id: uuid.UUID | None
    notes: str | None
    model_config = {"from_attributes": True}
