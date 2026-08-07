import uuid
from decimal import Decimal

from pydantic import BaseModel


class SpendingBucketOut(BaseModel):
    key: str
    key_id: uuid.UUID | None
    total: Decimal
    count: int
