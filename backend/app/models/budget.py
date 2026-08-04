import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Budget(Base, UUIDMixin, TimestampMixin):
    """One category's budgeted amount for one calendar month.

    `month` is always the first of the month — the date column IS the period, so there
    is no separate period-type or period-length concept to keep in sync with it. The
    unique constraint is what makes `services/budgets.py::upsert` an upsert instead of a
    create-or-fail: calling it twice for the same household/category/month updates the
    one row rather than erroring or duplicating.

    `rollover` opts this month's row into pulling forward whatever was left of last
    month's *effective* budget. The carried amount itself is never stored anywhere —
    see `rollover_carry` — so flipping this flag off can never corrupt a number that was
    already written to `amount`.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("household_id", "category_id", "month", name="uq_budget_period"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE")
    )
    month: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    rollover: Mapped[bool] = mapped_column(Boolean, default=False)
