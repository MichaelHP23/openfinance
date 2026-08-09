from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.session import UserSession
from app.services import auth


def test_register_creates_household_and_owner(db):
    user = auth.register(db, "a@example.com", "pw12345")
    assert user.email == "a@example.com"
    assert user.role.value == "owner"
    assert user.household_id is not None


def test_register_duplicate_email_raises(db):
    auth.register(db, "a@example.com", "pw12345")
    with pytest.raises(auth.EmailTaken):
        auth.register(db, "a@example.com", "other")


def test_authenticate_ok_and_bad(db):
    auth.register(db, "a@example.com", "pw12345")
    assert auth.authenticate(db, "a@example.com", "pw12345") is not None
    assert auth.authenticate(db, "a@example.com", "nope") is None
    assert auth.authenticate(db, "missing@example.com", "pw") is None


def test_session_issue_and_resolve(db):
    user = auth.register(db, "a@example.com", "pw12345")
    token = auth.issue_session(db, user)
    resolved = auth.resolve_session(db, token)
    assert resolved is not None and resolved.id == user.id
    assert auth.resolve_session(db, "garbage") is None


def test_resolve_session_rejects_idle_past_timeout(db):
    user = auth.register(db, "idle@example.com", "pw12345")
    token = auth.issue_session(db, user)
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == auth.hash_token(token)))
    sess.last_seen_at = datetime.now(UTC) - auth.IDLE_TIMEOUT - timedelta(seconds=1)
    db.commit()
    assert auth.resolve_session(db, token) is None


def test_resolve_session_touches_last_seen_at(db):
    user = auth.register(db, "touch@example.com", "pw12345")
    token = auth.issue_session(db, user)
    auth.resolve_session(db, token)
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == auth.hash_token(token)))
    assert sess.last_seen_at is not None


def test_change_password_rotates_and_invalidates_other_sessions(db):
    user = auth.register(db, "rot@example.com", "pw12345")
    old_token = auth.issue_session(db, user)
    new_token = auth.change_password(db, user, "pw12345", "newpassword")
    assert auth.resolve_session(db, old_token) is None
    assert auth.resolve_session(db, new_token) is not None
    assert auth.authenticate(db, "rot@example.com", "newpassword") is not None


def test_change_password_wrong_current_raises(db):
    user = auth.register(db, "wrongpw@example.com", "pw12345")
    with pytest.raises(auth.WrongPassword):
        auth.change_password(db, user, "not-it", "newpassword")


def test_list_and_revoke_sessions(db):
    user = auth.register(db, "multi@example.com", "pw12345")
    t1 = auth.issue_session(db, user)
    t2 = auth.issue_session(db, user)
    sessions = auth.list_sessions(db, user.id)
    assert len(sessions) == 2

    target = next(s for s in sessions if s.token_hash == auth.hash_token(t1))
    assert auth.revoke_session(db, user.id, target.id) is True
    assert auth.resolve_session(db, t1) is None
    assert auth.resolve_session(db, t2) is not None
    # revoking someone else's session id is a no-op, not an error
    other = auth.register(db, "other@example.com", "pw12345")
    other_token = auth.issue_session(db, other)
    other_sess = db.scalar(
        select(UserSession).where(UserSession.token_hash == auth.hash_token(other_token))
    )
    assert auth.revoke_session(db, user.id, other_sess.id) is False


def test_revoke_other_sessions_keeps_the_current_one(db):
    user = auth.register(db, "keep@example.com", "pw12345")
    keep = auth.issue_session(db, user)
    auth.issue_session(db, user)
    auth.issue_session(db, user)
    revoked = auth.revoke_other_sessions(db, user.id, auth.hash_token(keep))
    assert revoked == 2
    assert auth.resolve_session(db, keep) is not None
    assert len(auth.list_sessions(db, user.id)) == 1
