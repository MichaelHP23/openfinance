"""goals: savings and debt-payoff targets, and which accounts count toward them

Revision ID: f4a29c7d1e63
Revises: c8a4f21d9b6e
Create Date: 2026-08-01

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a29c7d1e63"
down_revision: Union[str, Sequence[str], None] = "c8a4f21d9b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the explicit .create() calls in upgrade() own these types, same
# pattern as b2c3d4e5f6a7 (recurring_series) — Postgres does not drop an enum with
# its table, so downgrade() has to drop these explicitly too.
goal_kind = postgresql.ENUM("savings", "debt_payoff", name="goal_kind", create_type=False)
goal_status = postgresql.ENUM(
    "active", "achieved", "archived", name="goal_status", create_type=False
)


def upgrade() -> None:
    goal_kind.create(op.get_bind(), checkfirst=True)
    goal_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", goal_kind, nullable=False),
        sa.Column("target_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("monthly_funding", sa.Numeric(19, 4), nullable=True),
        sa.Column("status", goal_status, nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goals_household_id"), "goals", ["household_id"])

    op.create_table(
        "goal_accounts",
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("goal_id", "account_id"),
    )


def downgrade() -> None:
    op.drop_table("goal_accounts")
    op.drop_index(op.f("ix_goals_household_id"), table_name="goals")
    op.drop_table("goals")
    goal_status.drop(op.get_bind(), checkfirst=True)
    goal_kind.drop(op.get_bind(), checkfirst=True)
