from datetime import UTC, datetime, timedelta

import pytest

from app.models.household_invite import HouseholdInvite
from app.services import auth, invites


def test_create_invite_returns_row_and_raw_token(db):
    owner = auth.register(db, "owner@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    assert invite.token_hash != raw
    assert invite.used_at is None
    assert invite.role.value == "member"


def test_join_places_new_user_in_inviting_household_as_member(db):
    owner = auth.register(db, "owner2@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    joined = invites.join(db, raw, "newmember@example.com", "pw12345")
    assert joined.household_id == owner.household_id
    assert joined.role.value == "member"


def test_join_marks_invite_used(db):
    owner = auth.register(db, "owner3@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw, "newmember2@example.com", "pw12345")
    db.refresh(invite)
    assert invite.used_at is not None


def test_join_rejects_already_used_token(db):
    owner = auth.register(db, "owner4@example.com", "pw12345")
    _, raw = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw, "first@example.com", "pw12345")
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, raw, "second@example.com", "pw12345")


def test_join_rejects_expired_token(db):
    owner = auth.register(db, "owner5@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, raw, "toolate@example.com", "pw12345")


def test_join_rejects_unknown_token(db):
    with pytest.raises(invites.InvalidInvite):
        invites.join(db, "not-a-real-token", "nobody@example.com", "pw12345")


def test_join_still_rejects_taken_email(db):
    owner = auth.register(db, "owner6@example.com", "pw12345")
    auth.register(db, "taken@example.com", "pw12345")
    _, raw = invites.create_invite(db, owner.household_id, owner.id)
    with pytest.raises(auth.EmailTaken):
        invites.join(db, raw, "taken@example.com", "pw12345")


def test_revoke_invite_removes_unused_only(db):
    owner = auth.register(db, "owner7@example.com", "pw12345")
    invite, raw = invites.create_invite(db, owner.household_id, owner.id)
    assert invites.revoke_invite(db, owner.household_id, invite.id) is True
    assert db.get(HouseholdInvite, invite.id) is None

    invite2, raw2 = invites.create_invite(db, owner.household_id, owner.id)
    invites.join(db, raw2, "used@example.com", "pw12345")
    assert invites.revoke_invite(db, owner.household_id, invite2.id) is False


def test_invites_isolated_by_household(db):
    owner1 = auth.register(db, "iso1@example.com", "pw12345")
    owner2 = auth.register(db, "iso2@example.com", "pw12345")
    invite, _ = invites.create_invite(db, owner1.household_id, owner1.id)
    assert invites.revoke_invite(db, owner2.household_id, invite.id) is False
    assert {i.id for i in invites.list_invites(db, owner1.household_id)} == {invite.id}
    assert invites.list_invites(db, owner2.household_id) == []
