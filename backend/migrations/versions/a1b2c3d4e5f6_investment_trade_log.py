"""investment trade log

Revision ID: a1b2c3d4e5f6
Revises: d5f2c1a83b70
Create Date: 2026-07-26

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "d5f2c1a83b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

trade_type = sa.Enum("buy", "sell", "dividend", "split", name="trade_type")


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("quote_symbol", sa.String(), nullable=True),
        sa.Column("is_manual_price", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "symbol", name="uq_security_symbol"),
    )
    op.create_index(op.f("ix_securities_household_id"), "securities", ["household_id"])
    op.create_index(op.f("ix_securities_symbol"), "securities", ["symbol"])

    trade_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("traded_on", sa.Date(), nullable=False),
        sa.Column("type", trade_type, nullable=False),
        sa.Column("quantity", sa.Numeric(19, 8), nullable=False),
        sa.Column("price_per_unit", sa.Numeric(19, 8), nullable=False),
        sa.Column("fees", sa.Numeric(19, 4), nullable=False),
        sa.Column("split_ratio", sa.Numeric(19, 8), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trades_household_id"), "trades", ["household_id"])
    op.create_index(op.f("ix_trades_account_id"), "trades", ["account_id"])
    op.create_index(op.f("ix_trades_security_id"), "trades", ["security_id"])
    op.create_index(op.f("ix_trades_traded_on"), "trades", ["traded_on"])
    op.create_index(op.f("ix_trades_external_id"), "trades", ["external_id"])

    op.create_table(
        "security_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priced_on", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(19, 8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("security_id", "priced_on", name="uq_price_day"),
    )
    op.create_index(op.f("ix_security_prices_security_id"), "security_prices", ["security_id"])
    op.create_index(op.f("ix_security_prices_priced_on"), "security_prices", ["priced_on"])


def downgrade() -> None:
    op.drop_table("security_prices")
    op.drop_table("trades")
    op.drop_table("securities")
    # Postgres does not drop an enum with its table. `account_type` in 199492b35732 has
    # exactly that bug; a re-upgrade there fails on "type already exists". Not repeated.
    trade_type.drop(op.get_bind(), checkfirst=True)
