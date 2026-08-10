from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False


def _member_client(db, owner_client) -> TestClient:
    invite = owner_client.post("/auth/invites").json()
    c = csrf_client(app, db, get_db)
    c.post(
        "/auth/join",
        json={"token": invite["token"], "email": "member@example.com", "password": "pw12345"},
    )
    return c


def test_owner_can_create_and_list_invites(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own@example.com", "password": "pw12345"})
    r = c.post("/auth/invites")
    assert r.status_code == 200
    assert "token" in r.json()

    r2 = c.get("/auth/invites")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_member_cannot_create_invites(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own2@example.com", "password": "pw12345"})
    member = _member_client(db, c)
    r = member.post("/auth/invites")
    assert r.status_code == 403


def test_member_joins_inviting_household_and_can_reach_household_routes(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own3@example.com", "password": "pw12345"})
    owner_household = c.get("/auth/me").json()["household_id"]
    member = _member_client(db, c)
    me = member.get("/auth/me").json()
    assert me["household_id"] == owner_household
    assert me["role"] == "member"
    # member reads/writes day-to-day data fine
    assert member.get("/accounts").status_code == 200
    assert member.post("/accounts", json={"type": "checking", "name": "Shared"}).status_code == 200


def test_member_blocked_from_owner_only_routes_with_403_not_500(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own4@example.com", "password": "pw12345"})
    member = _member_client(db, c)
    assert member.get("/connections").status_code == 403
    assert member.get("/documents").status_code == 403
    assert member.get("/tax/realized-gains?year=2026").status_code == 403
    assert member.get("/export/all.zip").status_code == 403
    assert member.get("/auth/invites").status_code == 403


def test_owner_reaches_previously_owner_gated_routes(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "own5@example.com", "password": "pw12345"})
    assert c.get("/connections").status_code == 200
    assert c.get("/documents").status_code == 200
