import re

from fastapi.testclient import TestClient

from app.main import LOOPBACK_ORIGIN_RE, app


def _preflight(origin: str):
    return TestClient(app).options(
        "/auth/login",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


def test_any_localhost_port_is_allowed_in_development():
    # Vite's port hopping means the dev origin is not knowable in advance.
    resp = _preflight("http://localhost:5187")
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5187"
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_remote_origins_are_still_rejected():
    resp = _preflight("http://evil.example.com")
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_regex_does_not_match_lookalike_hosts():
    pattern = re.compile(LOOPBACK_ORIGIN_RE)
    assert pattern.match("http://localhost:5173")
    assert pattern.match("http://127.0.0.1")
    # Anchored on both ends, so these must not slip through.
    assert not pattern.match("http://localhost.evil.com")
    assert not pattern.match("http://notlocalhost:5173")
    assert not pattern.match("https://localhost:5173.evil.com")
