"""Live dispatch board + map + two-way SMS (Phase 11): add users' live
location-ping columns and messages.channel — loads the checked-in SQL
verbatim.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0010_dispatch_board.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS ck_messages_channel")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS channel")
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_current_latlng_pair"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS current_longitude")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS current_latitude")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS location_updated_at")
