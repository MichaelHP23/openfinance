from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db

app.state.limiter.enabled = False


def client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_register_login_me_flow(db):
    c = client(db)
    r = c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["email"] == "a@example.com"
    assert "session" in r.cookies

    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


def test_me_requires_auth(db):
    c = TestClient(app)  # no cookie
    app.dependency_overrides[get_db] = lambda: db
    assert c.get("/auth/me").status_code == 401


def test_duplicate_register_conflicts(db):
    c = client(db)
    c.post("/auth/register", json={"email": "a@example.com", "password": "pw12345"})
    r = c.post("/auth/register", json={"email": "a@example.com", "password": "x"})
    assert r.status_code == 409


def test_login_success_and_bad_password(db):
    c = client(db)
    c.post("/auth/register", json={"email": "b@example.com", "password": "pw12345"})
    c2 = client(db)
    r = c2.post("/auth/login", json={"email": "b@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert "session" in r.cookies

    r_bad = c2.post("/auth/login", json={"email": "b@example.com", "password": "wrong"})
    assert r_bad.status_code == 401


def test_logout_clears_cookie(db):
    c = client(db)
    c.post("/auth/register", json={"email": "c@example.com", "password": "pw12345"})
    r = c.post("/auth/logout")
    assert r.status_code == 200
    assert "session" not in c.cookies
