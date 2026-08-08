"""documents (encrypted vault) and accounts.beneficiary

Revision ID: b7e4a591c3d0
Revises: f4a29c7d1e63
Create Date: 2026-08-01

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e4a591c3d0"
down_revision: Union[str, Sequence[str], None] = "f4a29c7d1e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

document_kind = postgresql.ENUM(
    "will", "trust", "insurance", "deed", "title", "statement", "other",
    name="document_kind", create_type=False,
)


def upgrade() -> None:
    document_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", document_kind, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("ciphertext_path", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_household_id"), "documents", ["household_id"])
    op.add_column("accounts", sa.Column("beneficiary", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "beneficiary")
    op.drop_index(op.f("ix_documents_household_id"), table_name="documents")
    op.drop_table("documents")
    # Postgres does not drop an enum with its table — same fix as every prior migration.
    document_kind.drop(op.get_bind(), checkfirst=True)
