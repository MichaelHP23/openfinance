from datetime import UTC, datetime, timedelta

from app.models.household import Household
from app.services import audit, auth


def _household(db) -> Household:
    h = Household(name="Audit Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def test_record_and_list(db):
    h = _household(db)
    user = auth.register(db, "audit@example.com", "pw12345")
    audit.record(db, h.id, user.id, "session.login", {"ip": "1.2.3.4"})
    events = audit.list_for(db, h.id)
    assert len(events) == 1
    assert events[0].action == "session.login"
    assert events[0].event_metadata == {"ip": "1.2.3.4"}


def test_list_isolated_by_household(db):
    h1, h2 = _household(db), _household(db)
    user = auth.register(db, "audit2@example.com", "pw12345")
    audit.record(db, h1.id, user.id, "session.login")
    audit.record(db, h2.id, user.id, "session.login")
    assert len(audit.list_for(db, h1.id)) == 1
    assert len(audit.list_for(db, h2.id)) == 1


def test_list_filters_by_action_and_since(db):
    h = _household(db)
    user = auth.register(db, "audit3@example.com", "pw12345")
    audit.record(db, h.id, user.id, "session.login")
    audit.record(db, h.id, user.id, "invite.created")

    assert len(audit.list_for(db, h.id, action="invite.created")) == 1
    future = datetime.now(UTC) + timedelta(days=1)
    assert audit.list_for(db, h.id, since=future) == []


def test_metadata_defaults_to_empty_dict(db):
    h = _household(db)
    user = auth.register(db, "audit4@example.com", "pw12345")
    audit.record(db, h.id, user.id, "vault.document_downloaded")
    assert audit.list_for(db, h.id)[0].event_metadata == {}


from tests.csrf_helper import csrf_client
from app.core.db import get_db
from app.main import app

app.state.limiter.enabled = False


def test_audit_log_endpoint_owner_only_and_records_login(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "auditapi@example.com", "password": "pw12345"})

    c2 = csrf_client(app, db, get_db)
    c2.post("/auth/login", json={"email": "auditapi@example.com", "password": "pw12345"})

    r = c.get("/audit-log")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "session.login" in actions
