"""Add optional industry classification to public marketing leads.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-10
"""
from pathlib import Path

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0026_marketing_lead_industry.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_marketing_leads_industry;
        ALTER TABLE marketing_leads
            DROP CONSTRAINT IF EXISTS ck_marketing_leads_industry,
            DROP COLUMN IF EXISTS industry;
        """
    )
