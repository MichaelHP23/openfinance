from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://openfinance:openfinance@localhost:5432/openfinance"
    redis_url: str = "redis://localhost:6379/0"
    app_secret_key: str = "dev-only-insecure-change-me-32-bytes!!"
    environment: str = "development"
    # Comma-separated exact origins. Credentialed CORS forbids "*", so this is never a wildcard.
    cors_origins: str = "http://localhost:5173"
    # Single-user desktop mode: every request runs as one local household, no login.
    # There is NO authentication when this is on — only ever bind to localhost.
    local_mode: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
