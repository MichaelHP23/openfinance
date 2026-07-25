from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://openfinance:openfinance@localhost:5432/openfinance"
    redis_url: str = "redis://localhost:6379/0"
    app_secret_key: str = "dev-only-insecure-change-me-32-bytes!!"
    environment: str = "development"


settings = Settings()
