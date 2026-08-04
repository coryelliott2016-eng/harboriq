"""Stripe Connect, refunds, dunning cadence (Phase 8) — loads the checked-in
SQL verbatim.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0007_stripe_connect.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refunds")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS last_reminder_sent_at")
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS stripe_connect_account_id")
