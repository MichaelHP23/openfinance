import pytest
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
