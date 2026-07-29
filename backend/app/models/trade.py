import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TradeType(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    split = "split"


class Trade(Base, UUIDMixin, TimestampMixin):
    """One row of the trade log — the only thing in this feature a human types.

    Everything else (holdings, cost base, realized gains, returns) is derived by
    replaying these in date order, so a wrong row is fixed by editing the row, not by
    unwinding a stored balance.
    """

    __tablename__ = "trades"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), index=True
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), index=True
    )
    traded_on: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[TradeType] = mapped_column(Enum(TradeType, name="trade_type"))

    # Buy/sell: units traded, always positive — direction comes from `type`, not sign.
    # Dividend: units the payment was on, or 0 if unknown. Split: unused.
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), default=Decimal(0))
    # Buy/sell: price per unit. Dividend: per-unit payment, or 0 with the whole payment
    # here and `quantity` 0. A dividend's cash is therefore
    # `quantity * price_per_unit if quantity else price_per_unit` — slightly ugly, but it
    # keeps "total amount" derived rather than stored next to inputs it can disagree with.
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(19, 8), default=Decimal(0))
    fees: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal(0))
    # New shares per old share. 2 for a 2-for-1, 0.5 for a 1-for-2 reverse split.
    # Only read when type == split.
    split_ratio: Mapped[Decimal | None] = mapped_column(Numeric(19, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(nullable=True)
    # sha256(date|type|symbol|qty|price|account) — lets a CSV re-import be idempotent,
    # exactly as csv_import.py does for transactions.
    external_id: Mapped[str | None] = mapped_column(nullable=True, index=True)
