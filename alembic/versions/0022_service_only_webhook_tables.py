"""Revoke app-role access to cross-tenant webhook idempotency tables (M-2).

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-11
"""
from pathlib import Path

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SQL_FILE = (
    Path(__file__).resolve().parent.parent / "sql" / "0022_service_only_webhook_tables.sql"
)


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    # Restore the pre-0022 grants. Comments are left in place (harmless).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE stripe_processed_events "
        "TO harboriq_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE crypto_processed_events "
        "TO harboriq_app"
    )
