"""budgets: one category's amount per household per month

Revision ID: c8a4f21d9b6e
Revises: e1f3a2c4b508
Create Date: 2026-07-31

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8a4f21d9b6e"
down_revision: Union[str, Sequence[str], None] = "e1f3a2c4b508"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("rollover", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id", "category_id", "month", name="uq_budget_period"
        ),
    )
    op.create_index(op.f("ix_budgets_household_id"), "budgets", ["household_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_budgets_household_id"), table_name="budgets")
    op.drop_table("budgets")
