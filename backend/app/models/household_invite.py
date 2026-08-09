"""A shareable-link invite. No email is ever sent — the owner copies the link
themselves. See docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.4
for why: this app has no SMTP anywhere and pitches itself as having no third party
watching your data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.user import Role


class HouseholdInvite(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "household_invites"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    # Every invite this phase issues is Role.member — the column reuses the existing
    # `role` Postgres enum rather than a narrower type, since narrowing it would be a
    # migration of its own the day a second invite role ships.
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
