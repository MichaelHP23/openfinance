import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Cadence(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class SeriesStatus(str, enum.Enum):
    active = "active"
    ended = "ended"          # detection stopped seeing charges
    cancelled = "cancelled"  # the user says they cancelled it
    ignored = "ignored"      # the user says this isn't a subscription


class RecurringSeries(Base, UUIDMixin, TimestampMixin):
    """A repeating charge or deposit, inferred from transaction history.

    Derived columns are recomputed from scratch on every detection run; the user-owned
    ones (label, status, cancel_url, notes) survive it. That split is the whole reason
    the row is keyed on merchant_key rather than on an id detection invents each time.
    """

    __tablename__ = "recurring_series"
    __table_args__ = (
        UniqueConstraint("household_id", "merchant_key", name="uq_recurring_merchant"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    # The account most of the charges land on — informational, not a constraint. A card
    # that gets replaced moves the series without breaking it.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    merchant_key: Mapped[str] = mapped_column(String, index=True)
    label: Mapped[str] = mapped_column(String)  # user-editable; defaults to the raw name

    cadence: Mapped[Cadence] = mapped_column(Enum(Cadence, name="recurring_cadence"))
    status: Mapped[SeriesStatus] = mapped_column(
        Enum(SeriesStatus, name="recurring_status"), default=SeriesStatus.active
    )
    # Positive for money in (a paycheck), negative for money out. Sign is part of the
    # series identity, so the same employer's refund is a different row.
    direction: Mapped[int] = mapped_column(Integer)

    typical_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    last_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    amount_varies: Mapped[bool] = mapped_column(default=False)
    # Set only when the latest charge is >= $1 and >= 10% above the prior median.
    price_increase_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(19, 4), nullable=True
    )

    charge_count: Mapped[int] = mapped_column(Integer)
    first_charged_on: Mapped[date] = mapped_column(Date)
    last_charged_on: Mapped[date] = mapped_column(Date)
    next_expected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer)  # 0-100

    # Where the user goes to cancel. Pasted by hand — nothing knows this automatically.
    cancel_url: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
