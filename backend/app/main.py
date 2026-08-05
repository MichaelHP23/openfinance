from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    accounts,
    auth,
    budgets,
    categories,
    category_rules,
    connections,
    forecast,
    goals,
    imports,
    insights,
    investments,
    recurring,
    transactions,
)
from app.api.deps import limiter
from app.core.config import DEFAULT_SECRET_KEY, settings
from app.core.scheduler import lifespan

if settings.app_secret_key == DEFAULT_SECRET_KEY:
    # This key derives the KEK for provider credentials. The default is published in
    # the repo, so anything encrypted under it is effectively plaintext. Deliberately
    # unconditional: LOCAL_MODE pins ENVIRONMENT=development, so an environment-gated
    # guard is off in precisely the configuration that gets deployed.
    raise RuntimeError("APP_SECRET_KEY is still the published default — set a real one")

if settings.local_mode and settings.environment != "development":
    # LOCAL_MODE disables authentication outright. Refuse to start in any config that
    # looks like it faces a network.
    raise RuntimeError("LOCAL_MODE requires ENVIRONMENT=development — it has no authentication")

# Vite hops to the next free port whenever one is taken, so a dev frontend can land on
# any of 5173/5174/5175/… Listing them one by one is whack-a-mole; in development, trust
# private addresses on any port: loopback, RFC1918 LAN, and Tailscale (100.64/10 and
# *.ts.net) so a phone on the tailnet works. Anything routable from the public internet
# still has to be on the exact allowlist.
#
# This is not the security boundary — CORS restrains browsers, not attackers. Whatever
# can reach this port can call it, which is why LOCAL_MODE must stay on a private network.
LOOPBACK_ORIGIN_RE = (
    r"^http://("
    r"localhost|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
    r"|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net"
    r")(:\d+)?$"
)

app = FastAPI(title="OpenFinance API", lifespan=lifespan)
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
app.include_router(budgets.router)
app.include_router(categories.router)
app.include_router(category_rules.router)
app.include_router(transactions.router)
app.include_router(imports.router)
app.include_router(connections.router)
app.include_router(forecast.router)
app.include_router(goals.router)
app.include_router(insights.router)
app.include_router(investments.router)
app.include_router(recurring.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
