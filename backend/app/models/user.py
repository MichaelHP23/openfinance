import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Role(str, enum.Enum):
    owner = "owner"
    member = "member"
    viewer = "viewer"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column()
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.owner)
    # Envelope-encrypted with app.core.encryption (same AES-GCM scheme as provider
    # credentials and vault documents) — never stored or logged in the clear.
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
