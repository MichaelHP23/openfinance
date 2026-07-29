import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Security(Base, UUIDMixin, TimestampMixin):
    """A tradeable thing, keyed by the symbol the user types.

    Scoped per household rather than global: the same symbol means different
    instruments on different exchanges, and one user's portfolio is not a reference
    database. `symbol` is stored uppercase and is the natural key the CSV import and
    the price fetcher both match on.
    """

    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("household_id", "symbol", name="uq_security_symbol"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # Symbol as the price provider knows it, when that differs from what the user types
    # (Yahoo wants "SHOP.TO", the user writes "SHOP"). Null means use `symbol`.
    quote_symbol: Mapped[str | None] = mapped_column(nullable=True)
    # Illiquid holdings — private company shares, a rental property. No provider will
    # ever quote these, so the only price they get is a manual one.
    is_manual_price: Mapped[bool] = mapped_column(Boolean, default=False)

    # ponytail: no `category_id` and no `is_benchmark` yet — they belong to tables and
    # features that do not exist in Phase 1. Both are nullable additions when they land.
