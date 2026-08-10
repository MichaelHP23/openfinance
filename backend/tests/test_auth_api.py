from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False


def client(db):
    return csrf_client(app, db, get_db)


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
    assert r.json()["status"] == "ok"
    assert "session" in c2.cookies

    r_bad = c2.post("/auth/login", json={"email": "b@example.com", "password": "wrong"})
    assert r_bad.status_code == 401


def test_logout_clears_cookie(db):
    c = client(db)
    c.post("/auth/register", json={"email": "c@example.com", "password": "pw12345"})
    r = c.post("/auth/logout")
    assert r.status_code == 200
    assert "session" not in c.cookies


def test_change_password_flow(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "pw@example.com", "password": "pw12345"})
    r = c.post(
        "/auth/password",
        json={"current_password": "pw12345", "new_password": "newpassword"},
    )
    assert r.status_code == 200
    # old cookie session is gone; new one from the response works
    r2 = c.get("/auth/me")
    assert r2.status_code == 200


def test_change_password_wrong_current_rejected(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "pw2@example.com", "password": "pw12345"})
    r = c.post(
        "/auth/password", json={"current_password": "nope", "new_password": "newpassword"}
    )
    assert r.status_code == 401


def test_list_and_revoke_sessions_api(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "sess@example.com", "password": "pw12345"})
    r = c.get("/auth/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True

    r2 = c.delete(f"/auth/sessions/{sessions[0]['id']}")
    assert r2.status_code == 200
    # revoked its own current session — /auth/me now fails
    assert c.get("/auth/me").status_code == 401


import time as _time

from app.services.totp import _hotp


def test_2fa_enroll_verify_and_two_step_login(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "flow2fa@example.com", "password": "pw12345"})
    enroll = c.post("/auth/2fa/enroll")
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    code = _hotp(secret, int(_time.time()) // 30)
    verify = c.post("/auth/2fa/verify", json={"code": code})
    assert verify.status_code == 200

    # a fresh (unauthenticated) client now needs two steps to log in
    c2 = csrf_client(app, db, get_db)
    login = c2.post("/auth/login", json={"email": "flow2fa@example.com", "password": "pw12345"})
    assert login.status_code == 200
    body = login.json()
    assert body["status"] == "totp_required"
    assert "session" not in c2.cookies

    login_code = _hotp(secret, int(_time.time()) // 30)
    finish = c2.post(
        "/auth/2fa/login-verify",
        json={"preauth_token": body["preauth_token"], "code": login_code},
    )
    assert finish.status_code == 200
    assert "session" in c2.cookies


def test_login_without_2fa_still_returns_status_ok(db):
    c = csrf_client(app, db, get_db)
    c.post("/auth/register", json={"email": "no2fa@example.com", "password": "pw12345"})
    c2 = csrf_client(app, db, get_db)
    r = c2.post("/auth/login", json={"email": "no2fa@example.com", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "session" in c2.cookies
