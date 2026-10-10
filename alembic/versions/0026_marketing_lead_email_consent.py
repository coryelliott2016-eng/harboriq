"""Record optional email-marketing consent and remove request identifiers.

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

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0026_marketing_lead_email_consent.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE marketing_leads
            DROP CONSTRAINT IF EXISTS ck_marketing_leads_email_consent_metadata,
            DROP COLUMN IF EXISTS marketing_email_consent_method,
            DROP COLUMN IF EXISTS marketing_email_consent_version,
            DROP COLUMN IF EXISTS marketing_email_consent_at,
            DROP COLUMN IF EXISTS marketing_email_opt_in,
            ADD COLUMN ip_hint INET,
            ADD COLUMN user_agent TEXT
        """
    )
