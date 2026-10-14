"""transactions: ignored flag and tags

Revision ID: a9c4e2f71b36
Revises: e7b3c9d2a415
Create Date: 2026-10-13

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9c4e2f71b36"
down_revision: Union[str, Sequence[str], None] = "e7b3c9d2a415"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "transactions",
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("transactions", "tags")
    op.drop_column("transactions", "ignored")
