"""category rules, transaction category index, system taxonomy seed

Revision ID: e1f3a2c4b508
Revises: b2c3d4e5f6a7
Create Date: 2026-07-30

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.services.categories import ensure_system_categories

revision: str = "e1f3a2c4b508"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the explicit .create() calls below own these types, matching the
# pattern established in a1b2c3d4e5f6.
rule_match_type = postgresql.ENUM(
    "merchant_contains",
    "merchant_exact",
    "merchant_regex",
    name="rule_match_type",
    create_type=False,
)
rule_source = postgresql.ENUM("user", "suggested", name="rule_source", create_type=False)


def upgrade() -> None:
    rule_match_type.create(op.get_bind(), checkfirst=True)
    rule_source.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "category_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_type", rule_match_type, nullable=False),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("min_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("max_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("source", rule_source, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_category_rules_household_id"), "category_rules", ["household_id"]
    )
    # spend_by_category over a decade of history is the only query here with real
    # growth; this is the index it wants.
    op.create_index(
        "ix_transactions_household_category_posted",
        "transactions",
        ["household_id", "category_id", "posted_at"],
    )
    ensure_system_categories(Session(bind=op.get_bind()))


def downgrade() -> None:
    op.drop_index("ix_transactions_household_category_posted", table_name="transactions")
    op.drop_table("category_rules")
    # Postgres does not drop an enum with its table — same fix as a1b2c3d4e5f6.
    rule_match_type.drop(op.get_bind(), checkfirst=True)
    rule_source.drop(op.get_bind(), checkfirst=True)
    # The seeded categories are deliberately left in place: transactions may reference
    # them, and a downgrade that orphans FKs is worse than a downgrade that leaves rows.
