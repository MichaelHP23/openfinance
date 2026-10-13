"""alerts: dismissals table, recurring_series.cancelled_on

Revision ID: e7b3c9d2a415
Revises: d84a2f6c9e17
Create Date: 2026-10-12

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3c9d2a415"
down_revision: Union[str, Sequence[str], None] = "d84a2f6c9e17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recurring_series", sa.Column("cancelled_on", sa.Date(), nullable=True))
    op.create_table(
        "alert_dismissals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "key", name="uq_alert_dismissal"),
    )
    op.create_index(
        "ix_alert_dismissals_household_id", "alert_dismissals", ["household_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_alert_dismissals_household_id", table_name="alert_dismissals")
    op.drop_table("alert_dismissals")
    op.drop_column("recurring_series", "cancelled_on")
