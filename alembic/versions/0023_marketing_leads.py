"""Add platform marketing_leads table for public GTM signup capture.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-12
"""
from pathlib import Path

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0023_marketing_leads.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing_leads")
