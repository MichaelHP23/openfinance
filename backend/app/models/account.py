import enum
import uuid
from decimal import Decimal
from sqlalchemy import ForeignKey, Enum, Numeric, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class AccountType(str, enum.Enum):
    checking = "checking"; savings = "savings"; credit_card = "credit_card"
    loan = "loan"; investment = "investment"; crypto = "crypto"
    cash = "cash"; asset = "asset"; liability = "liability"


class Account(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "accounts"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_connections.id"), nullable=True
    )
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"))
    name: Mapped[str] = mapped_column()
    institution: Mapped[str | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=True)
