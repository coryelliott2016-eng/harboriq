"""Company MFA policy (Phase 17, Area C.2): adds companies.mfa_required so
an owner/admin can force every user in the tenant to enroll MFA before
they can complete login -- loads the checked-in SQL verbatim.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0017_company_mfa_policy.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS mfa_required")
