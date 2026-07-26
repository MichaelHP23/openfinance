from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import accounts, auth, connections, imports, transactions
from app.api.deps import limiter
from app.core.config import DEFAULT_SECRET_KEY, settings

if settings.app_secret_key == DEFAULT_SECRET_KEY and settings.environment != "development":
    # This key derives the KEK for provider credentials. The default is published in
    # the repo, so anything encrypted under it is effectively plaintext.
    raise RuntimeError("APP_SECRET_KEY is still the published default — set a real one")

if settings.local_mode and settings.environment != "development":
    # LOCAL_MODE disables authentication outright. Refuse to start in any config that
    # looks like it faces a network.
    raise RuntimeError("LOCAL_MODE requires ENVIRONMENT=development — it has no authentication")

# Vite hops to the next free port whenever one is taken, so a dev frontend can land on
# any of 5173/5174/5175/… Listing them one by one is whack-a-mole; in development, trust
# loopback on any port. Anything else stays on the exact allowlist.
LOOPBACK_ORIGIN_RE = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

app = FastAPI(title="OpenFinance API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=LOOPBACK_ORIGIN_RE if settings.environment == "development" else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(imports.router)
app.include_router(connections.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
