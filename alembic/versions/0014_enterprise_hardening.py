"""Enterprise Hardening (Phase 16): MFA/TOTP -- `users.mfa_enabled_at` and a
new tenant-scoped `mfa_backup_codes` table -- loads the checked-in SQL
verbatim.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0014_enterprise_hardening.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mfa_backup_codes")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mfa_enabled_at")
