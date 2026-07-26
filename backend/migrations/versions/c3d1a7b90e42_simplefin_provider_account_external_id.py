"""simplefin provider, accounts.external_id

Revision ID: c3d1a7b90e42
Revises: f22784246e55
Create Date: 2026-07-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d1a7b90e42"
down_revision: Union[str, Sequence[str], None] = "f22784246e55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE provider ADD VALUE IF NOT EXISTS 'simplefin'")
    op.add_column("accounts", sa.Column("external_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_accounts_external_id"), "accounts", ["external_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_accounts_external_id"), table_name="accounts")
    op.drop_column("accounts", "external_id")
    # Postgres cannot remove a value from an enum type; 'simplefin' stays behind.
