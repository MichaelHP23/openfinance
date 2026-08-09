"""auth hardening: session idle timeout, TOTP columns, household invites, audit log

Revision ID: d84a2f6c9e17
Revises: b7e4a591c3d0
Create Date: 2026-08-09

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d84a2f6c9e17"
down_revision: Union[str, Sequence[str], None] = "b7e4a591c3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the "role" enum already exists (abd413a14ea9). Reused, not
# recreated — household_invites.role is the same Postgres type as users.role.
role_enum = postgresql.ENUM("owner", "member", "viewer", name="role", create_type=False)


def upgrade() -> None:
    op.add_column("sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_secret", sa.LargeBinary(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "household_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_household_invites_household_id"), "household_invites", ["household_id"]
    )
    op.create_index(
        op.f("ix_household_invites_token_hash"), "household_invites", ["token_hash"], unique=True
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_household_id"), "audit_events", ["household_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_household_id"), table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(op.f("ix_household_invites_token_hash"), table_name="household_invites")
    op.drop_index(op.f("ix_household_invites_household_id"), table_name="household_invites")
    op.drop_table("household_invites")

    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("sessions", "last_seen_at")
    # No enum drop: household_invites.role borrowed the existing "role" type
    # (create_type=False) rather than creating its own, so there is nothing to drop.
