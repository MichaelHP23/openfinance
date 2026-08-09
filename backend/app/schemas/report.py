import uuid
from decimal import Decimal

from pydantic import BaseModel


class SpendingBucketOut(BaseModel):
    key: str
    key_id: uuid.UUID | None
    total: Decimal
    count: int


class MonthFlowOut(BaseModel):
    month: str
    income: Decimal
    expense: Decimal
    net: Decimal


class YearInReviewOut(BaseModel):
    year: int
    total_in: Decimal
    total_out: Decimal
    savings_rate: Decimal | None
    biggest_category: str | None
    biggest_category_amount: Decimal | None
    biggest_transaction_merchant: str | None
    biggest_transaction_amount: Decimal | None
    new_subscriptions: list[str]
    cancelled_subscriptions: list[str]
    net_worth_delta: Decimal | None
