import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    action: str
    event_metadata: dict[str, Any]
    created_at: datetime
    model_config = {"from_attributes": True}
