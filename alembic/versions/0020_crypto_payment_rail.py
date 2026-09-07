"""Crypto payment rail (Phase 18): licensed-processor stablecoin payments.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-07
"""
from pathlib import Path

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0020_crypto_payment_rail.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crypto_processed_events")
    op.execute("DROP TABLE IF EXISTS crypto_payments")
    op.execute("DROP TYPE IF EXISTS crypto_payment_status")
