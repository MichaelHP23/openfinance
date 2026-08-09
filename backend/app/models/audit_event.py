"""Append-only. No service function in app/services/audit.py ever updates or deletes
a row — the only writes are record() and, transitively, whatever the test suite tears
down with the whole table.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AuditEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_events"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    # Python attribute can't be named `metadata` — that's DeclarativeBase's own
    # attribute. The DB column is still named "metadata", matching the spec's table.
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
