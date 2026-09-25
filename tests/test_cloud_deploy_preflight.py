from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

cloud_deploy_preflight = importlib.import_module("cloud_deploy_preflight")


def _write_env(tmp_path: Path, lines: list[str]) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def test_cloud_preflight_passes_with_render_neon_cloudflare_and_aws_toggle(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=render-neon",
            "CLOUD_BASE_PROVIDER=cloudflare",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
            "CLOUDFLARE_API_TOKEN=token",
            "CLOUDFLARE_ZONE_ID=zone",
            "AWS_BACKUP_ENABLED=true",
            "AWS_PROFILE=harboriq-backups",
            "AWS_DEFAULT_REGION=us-east-1",
            "BACKUP_S3_BUCKET=harboriq-backups",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path)])
    assert exit_code == 0


def test_cloud_preflight_passes_with_cli_required_aws_backups(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=render-neon",
            "CLOUD_BASE_PROVIDER=none",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
            "AWS_PROFILE=harboriq-backups",
            "AWS_DEFAULT_REGION=us-east-1",
            "BACKUP_S3_BUCKET=harboriq-backups",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path), "--require-aws-backups"])
    assert exit_code == 0


def test_cloud_preflight_fails_when_stack_is_not_render_neon(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=aws-ecs",
            "CLOUD_BASE_PROVIDER=none",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path)])
    assert exit_code == 1


def test_cloud_preflight_fails_for_missing_cloudflare_tokens(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=render-neon",
            "CLOUD_BASE_PROVIDER=cloudflare",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path)])
    assert exit_code == 1


def test_cloud_preflight_fails_when_aws_backup_toggle_lacks_bucket(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=render-neon",
            "CLOUD_BASE_PROVIDER=none",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
            "AWS_BACKUP_ENABLED=true",
            "AWS_PROFILE=harboriq-backups",
            "AWS_DEFAULT_REGION=us-east-1",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path)])
    assert exit_code == 1


def test_cloud_preflight_fails_when_aws_backup_toggle_lacks_region(tmp_path):
    env_path = _write_env(
        tmp_path,
        [
            "DEPLOY_TARGET_STACK=render-neon",
            "CLOUD_BASE_PROVIDER=none",
            "APP_ENV=production",
            "DATABASE_URL=postgres://app",
            "SERVICE_DATABASE_URL=postgres://service",
            "MFA_ENCRYPTION_KEY=abc",
            "APP_BASE_URL=https://app.example.com",
            "CORS_ALLOW_ORIGINS=https://app.example.com",
            "STRIPE_API_KEY=sk_live_x",
            "STRIPE_WEBHOOK_SECRET=whsec_x",
            "SMTP_HOST=smtp.example.com",
            "SMTP_USERNAME=user",
            "SMTP_PASSWORD=pass",
            "EMAIL_FROM_ADDRESS=no-reply@example.com",
            "AWS_BACKUP_ENABLED=true",
            "AWS_PROFILE=harboriq-backups",
            "BACKUP_S3_BUCKET=harboriq-backups",
        ],
    )

    exit_code = cloud_deploy_preflight.main(["--env-file", str(env_path)])
    assert exit_code == 1
