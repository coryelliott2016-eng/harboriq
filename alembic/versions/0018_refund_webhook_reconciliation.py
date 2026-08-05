"""Refund webhook reconciliation (Phase 17, Area E): adds a partial unique
index on refunds.stripe_refund_id so ON CONFLICT DO NOTHING can be used for
idempotent charge.refunded webhook handling -- loads the checked-in SQL
verbatim.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0018_refund_webhook_reconciliation.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_refunds_stripe_refund_id")
