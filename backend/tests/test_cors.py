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


def test_private_network_origins_are_allowed_in_development():
    """A phone on the tailnet or the LAN loads the page from a private address, so
    that origin has to pass — without opening the door to public hosts."""
    for origin in [
        "http://192.168.1.42:5173",
        "http://10.0.0.7:5173",
        "http://172.16.5.9:5173",
        "http://100.101.102.103:5173",
        "http://desktop.tail1234.ts.net:5173",
    ]:
        resp = _preflight(origin)
        assert resp.status_code == 200, origin
        assert resp.headers["access-control-allow-origin"] == origin


def test_public_and_lookalike_origins_are_still_refused():
    for origin in [
        "http://evil.example.com",
        "http://localhost.evil.com",
        "http://100.200.1.1:5173",  # outside Tailscale's 100.64/10 range
        "http://11.0.0.1:5173",  # not RFC1918
        "http://ts.net.evil.com",
    ]:
        assert _preflight(origin).status_code == 400, origin
