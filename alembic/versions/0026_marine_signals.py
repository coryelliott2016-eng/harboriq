"""Marine Signals source monitoring, reviewed briefs, and shop feedback.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-05
"""
from pathlib import Path

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0026_marine_signals.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marine_signal_feedback")
    op.execute("DROP TABLE IF EXISTS marine_signal_profiles")
    op.execute("DROP TABLE IF EXISTS marine_signals")
    op.execute("DROP TABLE IF EXISTS marine_signal_sources")
