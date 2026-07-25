from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import accounts, auth, imports, transactions
from app.api.deps import limiter
from app.core.config import settings

if settings.local_mode and settings.environment != "development":
    # LOCAL_MODE disables authentication outright. Refuse to start in any config that
    # looks like it faces a network.
    raise RuntimeError("LOCAL_MODE requires ENVIRONMENT=development — it has no authentication")

app = FastAPI(title="OpenFinance API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
