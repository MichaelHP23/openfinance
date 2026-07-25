import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import settings
from app.core.db import get_db
from app.main import app


@pytest.fixture
def local_client(db, monkeypatch):
    monkeypatch.setattr(settings, "local_mode", True)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_local_mode_serves_requests_without_a_cookie(local_client):
    me = local_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == deps.LOCAL_USER_EMAIL
    assert me.json()["local_mode"] is True


def test_local_mode_reuses_one_household(local_client):
    first = local_client.get("/auth/me").json()
    local_client.post("/accounts", json={"type": "checking", "name": "Main"})
    second = local_client.get("/auth/me").json()
    assert first["household_id"] == second["household_id"]
    assert [a["name"] for a in local_client.get("/accounts").json()] == ["Main"]


def test_auth_still_required_when_local_mode_is_off(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        assert TestClient(app).get("/auth/me").status_code == 401
    finally:
        app.dependency_overrides.clear()
