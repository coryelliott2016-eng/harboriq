#!/usr/bin/env python3
"""Validate HarborIQ production cloud deployment inputs before first go-live.

This script checks the concrete config needed by the current deployment plan:
Render + Neon runtime, optional Cloudflare edge ("cloud base"), and optional
AWS-backed off-host backups.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REQUIRED_RENDER_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "SERVICE_DATABASE_URL",
    "MFA_ENCRYPTION_KEY",
    "APP_BASE_URL",
    "CORS_ALLOW_ORIGINS",
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "EMAIL_FROM_ADDRESS",
)
ALLOWED_CLOUD_BASE_PROVIDERS = {"cloudflare", "firebase", "none", "other"}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _env_value(key: str, combined_env: dict[str, str]) -> str:
    return combined_env.get(key, "").strip()


def _is_true(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file (default: .env).",
    )
    parser.add_argument(
        "--require-aws-backups",
        action="store_true",
        help="Fail unless AWS backup bucket/region settings are present.",
    )
    parser.add_argument(
        "--scope-only",
        action="store_true",
        help="Validate only DEPLOY_TARGET_STACK and CLOUD_BASE_PROVIDER.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_file_values = _load_env_file(Path(args.env_file))
    combined_env = {**env_file_values, **os.environ}
    errors: list[str] = []

    deploy_stack = _env_value("DEPLOY_TARGET_STACK", combined_env)
    if deploy_stack != "render-neon":
        errors.append(
            "DEPLOY_TARGET_STACK must be set to 'render-neon' to lock the primary runtime."
        )

    cloud_base_provider = _env_value("CLOUD_BASE_PROVIDER", combined_env).lower()
    if cloud_base_provider not in ALLOWED_CLOUD_BASE_PROVIDERS:
        errors.append(
            "CLOUD_BASE_PROVIDER must be one of: cloudflare, firebase, none, other."
        )

    aws_backups_enabled = args.require_aws_backups
    if not args.scope_only:
        app_env = _env_value("APP_ENV", combined_env).lower()
        if app_env != "production":
            errors.append("APP_ENV must be 'production' for go-live.")

        for key in REQUIRED_RENDER_VARS:
            if not _env_value(key, combined_env):
                errors.append(f"Missing required Render/Neon setting: {key}")

        if cloud_base_provider == "cloudflare":
            if not _env_value("CLOUDFLARE_API_TOKEN", combined_env):
                errors.append("CLOUD_BASE_PROVIDER=cloudflare requires CLOUDFLARE_API_TOKEN.")
            if not _env_value("CLOUDFLARE_ZONE_ID", combined_env):
                errors.append("CLOUD_BASE_PROVIDER=cloudflare requires CLOUDFLARE_ZONE_ID.")

        aws_backups_enabled = aws_backups_enabled or _is_true(
            _env_value("AWS_BACKUP_ENABLED", combined_env)
        )

    if aws_backups_enabled:
        if not _env_value("BACKUP_S3_BUCKET", combined_env):
            errors.append("AWS backups enabled but BACKUP_S3_BUCKET is missing.")
        if not (
            _env_value("AWS_DEFAULT_REGION", combined_env)
            or _env_value("AWS_REGION", combined_env)
        ):
            errors.append("AWS backups enabled but AWS_DEFAULT_REGION/AWS_REGION is missing.")

    if errors:
        print("❌ HarborIQ cloud deploy preflight failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("✅ HarborIQ cloud deploy preflight passed.")
    print(f"   DEPLOY_TARGET_STACK={deploy_stack}")
    print(f"   CLOUD_BASE_PROVIDER={cloud_base_provider}")
    print(f"   AWS backups required={'yes' if aws_backups_enabled else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
