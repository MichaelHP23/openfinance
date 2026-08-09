from datetime import UTC, datetime, timedelta

from app.models.audit_event import AuditEvent
from app.models.household import Household
from app.models.household_invite import HouseholdInvite
from app.models.session import UserSession
from app.models.user import Role
from app.services.auth import register


def test_user_totp_fields_default(db):
    user = register(db, "a@example.com", "pw12345")
    assert user.totp_enabled is False
    assert user.totp_secret is None


def test_session_last_seen_at_is_nullable(db):
    user = register(db, "b@example.com", "pw12345")
    sess = UserSession(
        user_id=user.id, token_hash="x", expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    assert sess.last_seen_at is None


def test_household_invite_round_trip(db):
    h = Household(name="Test")
    db.add(h)
    db.commit()
    db.refresh(h)
    user = register(db, "c@example.com", "pw12345")

    invite = HouseholdInvite(
        household_id=h.id, role=Role.member, token_hash="hash",
        created_by=user.id, expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    assert invite.used_at is None
    assert invite.role == Role.member


def test_audit_event_round_trip(db):
    h = Household(name="Test2")
    db.add(h)
    db.commit()
    db.refresh(h)
    user = register(db, "d@example.com", "pw12345")

    event = AuditEvent(
        household_id=h.id, user_id=user.id, action="session.login",
        event_metadata={"ip": "1.2.3.4"},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    assert event.event_metadata == {"ip": "1.2.3.4"}
