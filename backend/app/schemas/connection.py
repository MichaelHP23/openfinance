import uuid
from datetime import datetime

from pydantic import BaseModel


class SimpleFinLink(BaseModel):
    setup_token: str


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    last_synced_at: datetime | None
    model_config = {"from_attributes": True}


class SyncOut(BaseModel):
    accounts_added: int
    accounts_updated: int
    transactions_added: int
    transactions_skipped: int
    errors: list[str]
