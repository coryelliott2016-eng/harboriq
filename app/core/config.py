"""Application configuration (pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # App role (RLS-enforced) — used for tenant-scoped request handling.
    database_url: str = (
        "postgresql+psycopg://harboriq_app:harboriq_app_pass@localhost:5432/harboriq"
    )
    # Service role (BYPASSRLS) — webhook resolution, public-token lookup, maintenance.
    service_database_url: str = (
        "postgresql+psycopg://harboriq_service:harboriq_service_pass@localhost:5432/harboriq"
    )

    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""


settings = Settings()
