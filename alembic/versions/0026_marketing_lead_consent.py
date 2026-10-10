"""Record explicit contact and independent marketing consent.

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

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0026_marketing_lead_consent.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE marketing_leads
            DROP COLUMN marketing_consent_at,
            DROP COLUMN marketing_consent,
            DROP COLUMN consent_version,
            DROP COLUMN contact_consent_at
        """
    )
