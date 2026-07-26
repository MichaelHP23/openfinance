import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BalanceSnapshot(Base, UUIDMixin, TimestampMixin):
    """One row per account per day. Balances are only knowable in the present, so
    history has to be recorded as it happens — a day not captured is gone for good."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_on", name="uq_snapshot_day"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    captured_on: Mapped[date] = mapped_column(Date, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(19, 4))
