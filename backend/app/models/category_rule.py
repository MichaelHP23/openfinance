import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class MatchType(str, enum.Enum):
    merchant_contains = "merchant_contains"
    merchant_exact = "merchant_exact"
    merchant_regex = "merchant_regex"


class RuleSource(str, enum.Enum):
    user = "user"           # written by hand, or confirmed from a transaction edit
    suggested = "suggested"  # confirmed from an LLM proposal


class CategoryRule(Base, UUIDMixin, TimestampMixin):
    """One condition set that assigns a category.

    A rule matches when every non-null condition holds. Rules are tried in `priority`
    order, lowest first, and the first match wins — so ordering is the whole conflict
    model. No precedence lattice, no scoring.
    """

    __tablename__ = "category_rules"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    match_type: Mapped[MatchType] = mapped_column(
        Enum(MatchType, name="rule_match_type")
    )
    pattern: Mapped[str] = mapped_column(String(200))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE")
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    source: Mapped[RuleSource] = mapped_column(
        Enum(RuleSource, name="rule_source"),
        default=RuleSource.user,
    )
