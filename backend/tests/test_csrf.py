from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app

app.state.limiter.enabled = False


def client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_get_issues_a_csrf_cookie(db):
    c = client(db)
    r = c.get("/health")
    assert "csrf_token" in r.cookies


def test_mutating_request_without_token_is_rejected(db):
    c = client(db)
    c.get("/health")  # picks up the csrf_token cookie
    r = c.post("/accounts", json={"type": "checking", "name": "X"})
    assert r.status_code == 401 or r.status_code == 403  # unauthenticated is fine too, but never a 500


def test_mutating_request_with_mismatched_token_is_rejected(db, monkeypatch):
    monkeypatch.setattr(settings, "local_mode", False)
    c = client(db)
    c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    c.cookies.set("csrf_token", "real-token")
    r = c.post(
        "/auth/password",
        json={"current_password": "pw12345", "new_password": "newpw123"},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_register_login_join_are_exempt(db):
    c = client(db)
    r = c.post("/auth/register", json={"email": "b@example.com", "password": "pw12345"})
    assert r.status_code == 200  # no X-CSRF-Token header sent, and it still works


def test_csrf_skipped_in_local_mode(db, monkeypatch):
    monkeypatch.setattr(settings, "local_mode", True)
    c = client(db)
    r = c.post("/accounts", json={"type": "checking", "name": "Local"})
    assert r.status_code == 200
