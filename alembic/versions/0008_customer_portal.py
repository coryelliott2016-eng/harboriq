"""Customer self-service portal: 'portal' token purpose + messages table —
loads the checked-in SQL verbatim.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0008_customer_portal.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    # Postgres cannot DROP a single enum value, so the token_purpose ENUM
    # extension is not reversible in-place -- same accepted, forward-only
    # trade-off 0005_auth_hardening.py already documents for 'user_invite'.
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TYPE IF EXISTS message_sender_type")
