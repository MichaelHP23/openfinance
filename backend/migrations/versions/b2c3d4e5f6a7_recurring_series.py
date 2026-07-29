"""recurring series

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-26

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: see a1b2c3d4e5f6 — the explicit .create() calls own these types.
recurring_cadence = postgresql.ENUM(
    "weekly",
    "biweekly",
    "monthly",
    "quarterly",
    "yearly",
    name="recurring_cadence",
    create_type=False,
)
recurring_status = postgresql.ENUM(
    "active", "ended", "cancelled", "ignored", name="recurring_status", create_type=False
)


def upgrade() -> None:
    recurring_cadence.create(op.get_bind(), checkfirst=True)
    recurring_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "recurring_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("merchant_key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("cadence", recurring_cadence, nullable=False),
        sa.Column("status", recurring_status, nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("typical_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("last_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("min_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("max_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("amount_varies", sa.Boolean(), nullable=False),
        sa.Column("price_increase_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("charge_count", sa.Integer(), nullable=False),
        sa.Column("first_charged_on", sa.Date(), nullable=False),
        sa.Column("last_charged_on", sa.Date(), nullable=False),
        sa.Column("next_expected_on", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("cancel_url", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "merchant_key", name="uq_recurring_merchant"),
    )
    op.create_index(
        op.f("ix_recurring_series_household_id"), "recurring_series", ["household_id"]
    )
    op.create_index(
        op.f("ix_recurring_series_merchant_key"), "recurring_series", ["merchant_key"]
    )


def downgrade() -> None:
    op.drop_table("recurring_series")
    # Postgres does not drop an enum with its table — see a1b2c3d4e5f6 for the same fix.
    recurring_cadence.drop(op.get_bind(), checkfirst=True)
    recurring_status.drop(op.get_bind(), checkfirst=True)
