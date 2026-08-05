"""Marina/Slip Management (Phase 15), part 2 of 2: slips (wet/dry-stack/
mooring), slip reservations with a btree_gist exclusion constraint
preventing overlapping bookings of the same slip, dry-stack launch-request
scheduling, and job_line_items extended (nullable job_id +
slip_reservation_id, using the `storage` kind migration 0015 added) so a
reservation's rental period bills through the existing invoicing machinery
-- loads the checked-in SQL verbatim.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0016_marina_slip_management.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_job_line_items_slip_reservation")
    op.execute(
        "ALTER TABLE job_line_items DROP CONSTRAINT IF EXISTS ck_job_line_items_storage_has_reservation"
    )
    op.execute(
        "ALTER TABLE job_line_items DROP CONSTRAINT IF EXISTS ck_job_line_items_exactly_one_source"
    )
    op.execute(
        "ALTER TABLE job_line_items DROP CONSTRAINT IF EXISTS fk_job_line_items_slip_reservation"
    )
    op.execute("ALTER TABLE job_line_items DROP COLUMN IF EXISTS slip_reservation_id")
    # job_id cannot be safely restored to NOT NULL by a downgrade if any
    # storage-kind (job_id IS NULL) rows were written in the meantime; a
    # real rollback of this phase would need to delete or reassign them
    # first. Left as NULL-able on downgrade -- this mirrors the codebase's
    # existing practice of DROP TYPE/TABLE-only downgrades elsewhere, none
    # of which attempt to fully re-tighten a loosened constraint either.
    op.execute("DROP TABLE IF EXISTS dry_stack_launch_requests")
    op.execute("DROP TYPE IF EXISTS dry_stack_launch_status")
    op.execute("DROP TABLE IF EXISTS slip_reservations")
    op.execute("DROP TYPE IF EXISTS slip_reservation_status")
    op.execute("DROP TABLE IF EXISTS slips")
    op.execute("DROP TYPE IF EXISTS slip_status")
    op.execute("DROP TYPE IF EXISTS slip_type")
