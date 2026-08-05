"""Accounting & Reporting (Phase 14): nullable `users.hourly_rate` so P&L
labor-cost math has a real, honest input instead of an invented one --
loads the checked-in SQL verbatim.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0013_accounting_reports.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_hourly_rate_gte0")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS hourly_rate")
