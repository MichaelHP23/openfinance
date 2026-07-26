from pydantic_settings import BaseSettings, SettingsConfigDict

# Published in the repo, so it protects nothing. Real installs must override it —
# it derives the KEK that encrypts provider credentials (bank access tokens).
DEFAULT_SECRET_KEY = "dev-only-insecure-change-me-32-bytes!!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://openfinance:openfinance@localhost:5432/openfinance"
    redis_url: str = "redis://localhost:6379/0"
    app_secret_key: str = DEFAULT_SECRET_KEY
    environment: str = "development"
    # Comma-separated exact origins. Credentialed CORS forbids "*", so this is never a
    # wildcard. 5174 is what Vite falls back to when 5173 is already taken (e.g. the
    # compose web container is up and you also run `npm run dev`).
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
    )
    # Single-user desktop mode: every request runs as one local household, no login.
    # There is NO authentication when this is on — only ever bind to localhost.
    local_mode: bool = False

    # Background sync + daily balance snapshot cadence. 0 disables the loop entirely.
    sync_interval_hours: float = 6.0

    # AI assistant. Without a key the insights endpoint reports itself unavailable
    # and the UI hides it — nothing is ever sent anywhere by default.
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
