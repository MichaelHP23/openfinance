"""Append-only audit trail. record() is called from the small set of sensitive call
sites named in docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.7 —
login, session revoke, invite lifecycle, 2FA enrollment, vault document
download/delete, provider connection add/delete. Not every mutation: a row for every
PATCH /transactions/{id} would be noise, not a trail worth reading.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


def record(
    db: Session,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            household_id=household_id, user_id=user_id, action=action,
            event_metadata=metadata or {},
        )
    )
    db.commit()


def list_for(
    db: Session,
    household_id: uuid.UUID,
    since: datetime | None = None,
    action: str | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.household_id == household_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.created_at >= since)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    return list(db.scalars(stmt.order_by(AuditEvent.created_at.desc())))
