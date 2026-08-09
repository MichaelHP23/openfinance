"""Shared by every existing test file that POSTs/PATCHes/DELETEs against a
non-local-mode client, now that CSRFMiddleware protects every mutating route."""

from fastapi.testclient import TestClient


def csrf_client(app, db, get_db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    token = c.get("/health").cookies["csrf_token"]
    c.headers.update({"X-CSRF-Token": token})
    return c
