import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentKind


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    title: str
    filename: str
    content_type: str
    size_bytes: int
    notes: str | None
    created_at: datetime
    model_config = {"from_attributes": True}
