import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

MAX_TAG_LENGTH = 32
MAX_TAGS = 10


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
    # Not Optional: the columns are NOT NULL, so an explicit null is a 422 here rather
    # than a 500 at commit. Left unset, `exclude_unset` keeps them out of the update.
    ignored: bool = False
    tags: list[str] = []

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        """Trim and lower-case, drop repeats, reject what is left if it breaks a limit."""
        tags = list(dict.fromkeys(t.strip().lower() for t in value))
        if any(not t or len(t) > MAX_TAG_LENGTH for t in tags):
            raise ValueError(f"a tag is 1 to {MAX_TAG_LENGTH} characters")
        if len(tags) > MAX_TAGS:
            raise ValueError(f"at most {MAX_TAGS} tags per transaction")
        return tags


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
    ignored: bool
    tags: list[str]
    model_config = {"from_attributes": True}
