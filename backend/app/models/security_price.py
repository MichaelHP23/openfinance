import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

MANUAL = "manual"


class SecurityPrice(Base, UUIDMixin, TimestampMixin):
    """Daily close per security, in the security's own currency.

    Modelled on `balance_snapshots`: one row per (security, day), unique, append-only
    in practice. A manual row always wins over a fetched one for the same day — that
    is the sheet's "Market Value (MANUAL INPUT)" column, generalised.
    """

    __tablename__ = "security_prices"
    __table_args__ = (UniqueConstraint("security_id", "priced_on", name="uq_price_day"),)

    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id", ondelete="CASCADE"), index=True
    )
    priced_on: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(19, 8))
    source: Mapped[str] = mapped_column(String(16), default=MANUAL)  # manual | yahoo | twelvedata
