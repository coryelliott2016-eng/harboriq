"""Offline-capable mobile field app (Phase 12): job_attachments (photos +
signatures) and job_time_entries (per-job clock in/out) — loads the checked-in
SQL verbatim.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0011_field_app.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_time_entries")
    op.execute("DROP TABLE IF EXISTS job_attachments")
    op.execute("DROP TYPE IF EXISTS job_attachment_kind")
