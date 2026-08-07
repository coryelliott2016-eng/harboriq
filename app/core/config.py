"""Application configuration (pydantic-settings)."""
from typing import Annotated

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Obvious placeholder so a real deployment cannot accidentally ship with it.
# >=32 bytes because HS256 keys shorter than the digest weaken the MAC (RFC 7518 §3.2).
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-before-deploying"  # noqa: S105 -- documented dev-only placeholder, not a real secret
MIN_JWT_SECRET_BYTES = 32

# Generated fresh at process start -- never a fixed value baked into source --
# used only when APP_ENV=development and MFA_ENCRYPTION_KEY is unset, so
# `users.mfa_secret_enc` encryption works out of the box locally without
# requiring every developer to generate their own key. Never used outside dev
# (enforced by `_require_strong_mfa_key_outside_development` below). A prior
# revision hardcoded a fixed key here; that static value is never used for
# anything beyond this repo's own dev fixtures, but a static high-entropy
# secret in source is a bad pattern regardless, so it's generated at runtime
# instead. Trade-off: restarting the dev server invalidates any MFA secret
# previously encrypted with the prior process's key -- acceptable for local
# dev, where re-enrolling MFA is a one-click action.
DEV_MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()


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

    # --- Crypto payments (Phase 18) ---
    # Disabled by default: no API route creates a provider checkout until the
    # explicit feature flag is on AND Stripe is configured.  An empty
    # CRYPTO_WEBHOOK_SECRET follows the established webhook safety policy:
    # development accepts local synthetic events with a warning, while every
    # non-development environment fail-closes with a 503 rather than trusting
    # an unsigned financial event.  HarborIQ is never an on-chain custodian;
    # Stripe (or a future licensed provider) handles stablecoin checkout and
    # settlement.
    crypto_payments_enabled: bool = False
    crypto_webhook_secret: str = ""

    # --- Asset tokenization (Phase 19) ---
    # Disabled by default: this compliance-sensitive feature records only a
    # draft intent to tokenize a marine asset, pending outside securities
    # counsel review. It MUST NOT be enabled in a real deployment without
    # that review; migration 0021 independently restricts every record to
    # status='draft' and the API exposes no issuance or transfer operation.
    asset_tokenization_enabled: bool = False

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
    # Redis-backed, per-IP fixed-window limiter — see `app/core/rate_limit.py`.
    # Phase 16: replaced the old in-process dict/threading.Lock implementation
    # so the limit is shared and consistent across every app process/pod
    # rather than reset per-instance. Thresholds/behavior unchanged from the
    # original in-process version.
    rate_limit_requests_per_window: int = 10
    rate_limit_window_seconds: int = 60

    # --- Invite tokens ---
    invite_ttl_hours: int = 24 * 7

    # --- Redis (Phase 16) ---
    # Backs the distributed rate limiter (app/core/rate_limit.py) and is the
    # Celery broker + result backend (app/core/celery_app.py). Defaults to a
    # local dev Redis on the standard port; docker-compose.yml's `redis`
    # service and DEPLOYMENT.md both use this same default in-cluster.
    redis_url: str = "redis://localhost:6379/0"

    # --- MFA / TOTP (Phase 16) ---
    # Fernet symmetric key (44-char urlsafe-base64, e.g. via
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
    # used to encrypt `users.mfa_secret_enc` at rest — see app/core/crypto.py.
    # Empty in development: a deterministic, obviously-insecure dev-only key
    # is substituted so MFA enrollment works out of the box locally, mirroring
    # the `DEV_JWT_SECRET` pattern above. Non-development environments MUST
    # set a real key (enforced below, same validator style as jwt_secret).
    mfa_encryption_key: str = ""

    # --- Off-host database backups (Phase 16) ---
    # All empty by default => `scripts/backup_db_s3.sh` runs local-only (pg_dump
    # + gzip to BACKUP_OUTPUT_DIR), mirroring the smtp_host/twilio_account_sid
    # graceful-degrade pattern above. Setting all three of
    # BACKUP_S3_BUCKET/AWS credentials (via the AWS CLI's own standard env
    # vars or an attached IAM role) turns on an additional `aws s3 cp` push
    # of each local dump to off-host, off-provider storage. Not consumed by
    # pydantic-settings directly (the backup script is a standalone shell
    # script, not part of the FastAPI app), documented here for discoverability.
    backup_s3_bucket: str = ""
    backup_s3_prefix: str = "harboriq-backups"

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

    # --- SMS transport (Phase 11) ---
    # Empty twilio_account_sid (the dev default) means "console transport":
    # app/services/sms.py logs the message instead of calling out, mirroring
    # smtp_host's exact graceful-degrade pattern above. Setting all three of
    # TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_FROM_NUMBER turns on real
    # delivery via a plain httpx POST to the Twilio REST API -- no `twilio`
    # PyPI SDK dependency, since httpx is already a dependency and a single
    # REST call is all sending a message requires.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # --- Observability ---
    # Empty (the default) means "Sentry is off": app/core/observability.py
    # never calls sentry_sdk.init(), mirroring the exact graceful-degrade
    # pattern stripe_billing.py and email.py already use for their own
    # optional external dependency (no API key/SMTP host configured -> the
    # feature is simply skipped, never an error). Setting SENTRY_DSN turns
    # on error/performance reporting with zero other code changes.
    sentry_dsn: str = ""

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

    @model_validator(mode="after")
    def _require_strong_mfa_key_outside_development(self) -> "Settings":
        if self.app_env == "development":
            return self
        if self.mfa_encryption_key in ("", DEV_MFA_ENCRYPTION_KEY):
            raise ValueError(
                "MFA_ENCRYPTION_KEY must be set to a real Fernet key when "
                f"APP_ENV={self.app_env!r} (try: python -c \"from cryptography.fernet "
                'import Fernet; print(Fernet.generate_key().decode())\")'
            )
        return self

    @property
    def effective_mfa_encryption_key(self) -> str:
        """The Fernet key to actually use: configured value, or the fixed
        dev-only placeholder when running locally with none set."""
        return self.mfa_encryption_key or DEV_MFA_ENCRYPTION_KEY


settings = Settings()
