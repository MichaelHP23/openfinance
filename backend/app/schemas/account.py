import uuid
from decimal import Decimal

from pydantic import BaseModel


class AccountCreate(BaseModel):
    type: str
    name: str
    institution: str | None = None
    currency: str = "USD"
    balance: Decimal = Decimal(0)


class AccountOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    institution: str | None
    currency: str
    balance: Decimal
    is_manual: bool
    model_config = {"from_attributes": True}
