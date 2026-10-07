"""Idempotent weekly Marine Signals digest delivery ledger.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-05
"""
from pathlib import Path

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

SQL_FILE = (
    Path(__file__).resolve().parent.parent
    / "sql"
    / "0027_marine_signal_digest_delivery.sql"
)


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marine_signal_digest_deliveries")
