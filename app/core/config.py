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

    # --- Account lockout / rate limiting ---
    # After this many consecutive bad passwords, the account is locked for
    # `login_lockout_minutes` even against the correct password (see README,
    # "Auth" / "Known gaps"). Deliberately generous enough not to lock out a
    # user who fat-fingers a password a couple of times, tight enough to make
    # online guessing impractical.
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 15
    # In-process, per-IP sliding-window limiter — see `app/core/rate_limit.py`.
    # Deliberately NOT coordinated across instances; the natural upgrade once
    # horizontally scaled is a Redis-backed limiter (e.g. token bucket keyed
    # by IP in Redis, shared by every app process). One process today, so the
    # in-memory version is honestly proportionate rather than a real
    # production-scale guarantee.
    rate_limit_requests_per_window: int = 10
    rate_limit_window_seconds: int = 60

    # --- Invite tokens ---
    invite_ttl_hours: int = 24 * 7

    # --- Email transport ---
    # Empty smtp_host (the dev default) means "console transport": send_email
    # logs the message instead of dialing out, mirroring stripe_billing.py's
    # graceful degrade when stripe_api_key is unset. Setting smtp_host turns
    # on real delivery via smtplib.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from_address: str = "no-reply@harboriq.app"
    # The FRONTEND's origin (Vite dev server in development) — used to build
    # absolute links in emails, e.g. /accept-invite/:token and /pay/:token.
    # The API itself never renders these pages.
    app_base_url: str = "http://localhost:5173"

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
