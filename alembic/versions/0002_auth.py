"""Authentication + tenant onboarding — loads the checked-in SQL verbatim.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0002_auth.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_companies ON companies;")
    op.execute("ALTER TABLE companies NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE companies DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_sessions CASCADE;")
    op.execute("DROP INDEX IF EXISTS uq_users_email_global;")
    # Back to the free-text role column 0001 created.
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT;")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE TEXT USING role::text;")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'technician';")
    op.execute("DROP TYPE IF EXISTS user_role;")
