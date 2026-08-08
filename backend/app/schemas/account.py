import uuid
from decimal import Decimal

from pydantic import BaseModel


class AccountCreate(BaseModel):
    type: str
    name: str
    institution: str | None = None
    currency: str = "USD"
    balance: Decimal = Decimal(0)
    beneficiary: str | None = None


class AccountOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    institution: str | None
    currency: str
    balance: Decimal
    is_manual: bool
    beneficiary: str | None
    model_config = {"from_attributes": True}


class AccountUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    institution: str | None = None
    balance: Decimal | None = None
    beneficiary: str | None = None
