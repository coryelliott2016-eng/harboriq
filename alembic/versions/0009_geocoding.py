"""Geocoding integration (Phase 10): add users.address_text — loads the
checked-in SQL verbatim.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0009_geocoding.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS address_text")
