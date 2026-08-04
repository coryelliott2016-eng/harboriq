"""Application configuration (pydantic-settings)."""
from typing import Annotated

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Obvious placeholder so a real deployment cannot accidentally ship with it.
# >=32 bytes because HS256 keys shorter than the digest weaken the MAC (RFC 7518 §3.2).
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-before-deploying"
MIN_JWT_SECRET_BYTES = 32


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

    # --- Auth ---
    # HS256 shared secret for signing access tokens. Refresh tokens are opaque
    # random strings stored hashed in user_sessions, so they do not use this.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "harboriq"
    # Short access-token TTL bounds the window in which a revoked session's
    # access token still works (see README, "Auth").
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    password_reset_ttl_minutes: int = 60
    password_min_length: int = 12

    # --- CORS ---
    # Comma-separated in the env var (CORS_ALLOW_ORIGINS); defaults to the
    # Vite dev server so `npm run dev` works against a local API out of the
    # box. Production deployments must set this explicitly.
    # NoDecode tells pydantic-settings not to JSON-decode this env var before
    # validation runs — without it, a plain comma-separated string like
    # "http://a,http://b" fails as invalid JSON before our splitter ever sees
    # it. The before-validator below does the actual comma-splitting.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @model_validator(mode="before")
    @classmethod
    def _split_cors_allow_origins(cls, data):
        if isinstance(data, dict):
            raw = data.get("cors_allow_origins")
            if isinstance(raw, str):
                data["cors_allow_origins"] = [
                    origin.strip() for origin in raw.split(",") if origin.strip()
                ]
        return data

    @model_validator(mode="after")
    def _require_strong_jwt_secret_outside_development(self) -> "Settings":
        if self.app_env == "development":
            return self
        if self.jwt_secret in ("", DEV_JWT_SECRET):
            raise ValueError(
                "JWT_SECRET must be set to a strong random value when "
                f"APP_ENV={self.app_env!r} (try: openssl rand -hex 32)"
            )
        if len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes"
            )
        return self


settings = Settings()
