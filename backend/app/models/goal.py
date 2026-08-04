import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class GoalKind(str, enum.Enum):
    savings = "savings"
    debt_payoff = "debt_payoff"


class GoalStatus(str, enum.Enum):
    active = "active"
    achieved = "achieved"
    archived = "archived"


class Goal(Base, UUIDMixin, TimestampMixin):
    """A savings target or a debt to pay off.

    Progress is never stored here — it's always the summed *current* balance of the
    accounts in `goal_accounts`, computed at read time in
    `services/goals.py::progress_for`. There is deliberately no contributions ledger:
    a running total of "money put toward this goal" that can drift from what the
    linked account's real balance says is a bug factory, not a feature.
    """

    __tablename__ = "goals"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    name: Mapped[str] = mapped_column()
    kind: Mapped[GoalKind] = mapped_column(Enum(GoalKind, name="goal_kind"))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Null means "use the forecast's own projected surplus" — see
    # services/forecast.py::goal_projection.
    monthly_funding: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, name="goal_status"), default=GoalStatus.active
    )


class GoalAccount(Base):
    """Which balances count toward a goal.

    A pure link row — no id, no timestamp, because it carries no information beyond
    the pair itself. Both sides cascade: delete the goal or the account and the link
    disappears with it (ON DELETE CASCADE at the schema level, not a manual purge in
    services/goals.py — a link row has no meaning once either end of it is gone).
    """

    __tablename__ = "goal_accounts"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
