"""Shareable-link household invites. See app.models.household_invite for why the
column is Role rather than a narrower type, and the spec §2.4 for why this is a link
the owner copies themselves rather than an email this app has no way to send."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.household_invite import HouseholdInvite
from app.models.user import Role, User
from app.services.auth import EmailTaken

INVITE_TTL = timedelta(days=7)


class InvalidInvite(Exception):
    pass


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_invite(
    db: Session, household_id: uuid.UUID, created_by: uuid.UUID
) -> tuple[HouseholdInvite, str]:
    raw = secrets.token_urlsafe(32)
    invite = HouseholdInvite(
        household_id=household_id,
        role=Role.member,
        token_hash=_hash(raw),
        created_by=created_by,
        expires_at=datetime.now(UTC) + INVITE_TTL,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw


def list_invites(db: Session, household_id: uuid.UUID) -> list[HouseholdInvite]:
    return list(
        db.scalars(
            select(HouseholdInvite)
            .where(HouseholdInvite.household_id == household_id)
            .order_by(HouseholdInvite.created_at.desc())
        )
    )


def revoke_invite(db: Session, household_id: uuid.UUID, invite_id: uuid.UUID) -> bool:
    invite = db.scalar(
        select(HouseholdInvite).where(
            HouseholdInvite.id == invite_id, HouseholdInvite.household_id == household_id
        )
    )
    if not invite or invite.used_at is not None:
        return False
    db.delete(invite)
    db.commit()
    return True


def _resolve(db: Session, token: str) -> HouseholdInvite:
    invite = db.scalar(select(HouseholdInvite).where(HouseholdInvite.token_hash == _hash(token)))
    if not invite or invite.used_at is not None or invite.expires_at < datetime.now(UTC):
        raise InvalidInvite()
    return invite


def join(db: Session, token: str, email: str, password: str) -> User:
    invite = _resolve(db, token)
    if db.scalar(select(User).where(User.email == email)):
        raise EmailTaken(email)
    user = User(
        household_id=invite.household_id,
        email=email,
        password_hash=hash_password(password),
        role=invite.role,
    )
    db.add(user)
    invite.used_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return user
