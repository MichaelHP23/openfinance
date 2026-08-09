"""Double-submit CSRF, as an ASGI middleware rather than a per-route Depends — a
route-level dependency can't cleanly see the HTTP method to skip GETs, and a
middleware is one place a new mutating endpoint can't forget to wire up. See
docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.1.

SameSite=Lax on the session cookie already blocks classic cross-site form CSRF; this
closes the gap it leaves (same-site subdomain attacks, older browsers).
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

COOKIE = "csrf_token"
HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# None of these has a session yet to protect — the double-submit pattern has nothing
# to compare a token against until one exists.
EXEMPT_PATHS = {"/auth/register", "/auth/login", "/auth/join", "/auth/2fa/login-verify"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        needs_check = (
            not settings.local_mode
            and request.method not in SAFE_METHODS
            and request.url.path not in EXEMPT_PATHS
        )
        if needs_check:
            cookie_token = request.cookies.get(COOKIE)
            header_token = request.headers.get(HEADER)
            if not cookie_token or not header_token or not secrets.compare_digest(
                cookie_token, header_token
            ):
                return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)

        response = await call_next(request)

        if COOKIE not in request.cookies:
            response.set_cookie(
                COOKIE,
                secrets.token_urlsafe(32),
                httponly=False,  # the frontend must read it to send the header back
                samesite="lax",
                secure=settings.environment != "development",
            )
        return response
