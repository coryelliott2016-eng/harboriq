"""Auth hardening: lockout columns + user_invite token purpose — loads the
checked-in SQL verbatim.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-03
"""
from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0005_auth_hardening.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    # Postgres cannot DROP a single enum value, so the ENUM extension is not
    # reversible in-place; downgrading a deployment that has already accepted
    # invites would require a manual data migration. That's the accepted
    # trade-off for extending an existing enum instead of adding a new table
    # (see 0005_auth_hardening.sql) — it matches how 0002/0003/0004 also treat
    # their own enum additions as forward-only in practice.
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS locked_until;"
    )
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS failed_login_attempts;"
    )
