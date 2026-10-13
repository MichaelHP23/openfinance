"""One row per alert occurrence the household has dismissed.

Alerts themselves are never stored — services/alerts.py recomputes them on every read.
The key carries the date of the fact that raised the alert, so dismissing October's
bill does not hide November's.
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AlertDismissal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "alert_dismissals"
    __table_args__ = (UniqueConstraint("household_id", "key", name="uq_alert_dismissal"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    key: Mapped[str] = mapped_column(String)
