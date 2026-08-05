"""Marina/Slip Management (Phase 15), part 1 of 2: add the `storage` value to
the job_line_item_kind enum. Split from migration 0016 because Postgres
forbids using a brand-new enum value in the same transaction it was added in
-- see the SQL file's header comment.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0015_marina_slip_management.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    # PostgreSQL has no ALTER TYPE ... DROP VALUE. Removing an enum value
    # cleanly requires rebuilding the type (rename old, create new, cast
    # every column across); not attempted for a downgrade path, matching
    # this codebase's existing practice of DROP TABLE/TYPE-only downgrades
    # rather than fully reversing every additive DDL choice.
    pass
