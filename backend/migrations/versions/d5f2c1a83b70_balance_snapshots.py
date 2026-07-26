"""balance snapshots

Revision ID: d5f2c1a83b70
Revises: c3d1a7b90e42
Create Date: 2026-07-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5f2c1a83b70"
down_revision: Union[str, Sequence[str], None] = "c3d1a7b90e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "balance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "captured_on", name="uq_snapshot_day"),
    )
    op.create_index(
        op.f("ix_balance_snapshots_household_id"), "balance_snapshots", ["household_id"]
    )
    op.create_index(op.f("ix_balance_snapshots_account_id"), "balance_snapshots", ["account_id"])
    op.create_index(op.f("ix_balance_snapshots_captured_on"), "balance_snapshots", ["captured_on"])


def downgrade() -> None:
    op.drop_table("balance_snapshots")
