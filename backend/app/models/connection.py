import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, LargeBinary
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Provider(str, enum.Enum):
    manual = "manual"
    plaid = "plaid"


class ConnStatus(str, enum.Enum):
    active = "active"
    error = "error"
    disconnected = "disconnected"


class ProviderConnection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "provider_connections"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="provider"))
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[ConnStatus] = mapped_column(
        Enum(ConnStatus, name="conn_status"), default=ConnStatus.active
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
