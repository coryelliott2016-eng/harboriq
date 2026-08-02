"""Core CRM / operations domain — loads the checked-in SQL verbatim.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0003_crm_operations.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_line_items CASCADE;")

    # Jobs — drop the added columns, then restore 0001's tenant-blind FKs.
    op.execute("DROP INDEX IF EXISTS idx_jobs_company_vessel;")
    op.execute("DROP INDEX IF EXISTS idx_jobs_company_customer;")
    op.execute("DROP INDEX IF EXISTS idx_jobs_company_status_scheduled;")
    op.execute("DROP INDEX IF EXISTS idx_jobs_company_technician_scheduled;")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS ck_jobs_schedule_window;")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS ck_jobs_title_not_blank;")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_technician;")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_vessel;")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_customer;")
    op.execute("ALTER TABLE jobs ALTER COLUMN customer_id DROP NOT NULL;")
    op.execute(
        """
        ALTER TABLE jobs
            ADD CONSTRAINT jobs_customer_id_fkey
                FOREIGN KEY (customer_id) REFERENCES customers(id),
            ADD CONSTRAINT jobs_vessel_id_fkey
                FOREIGN KEY (vessel_id) REFERENCES vessels(id),
            ADD CONSTRAINT jobs_technician_id_fkey
                FOREIGN KEY (technician_id) REFERENCES users(id)
        """
    )
    op.execute(
        """
        ALTER TABLE jobs
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS hold_reason,
            DROP COLUMN IF EXISTS canceled_at,
            DROP COLUMN IF EXISTS completed_at,
            DROP COLUMN IF EXISTS started_at,
            DROP COLUMN IF EXISTS scheduled_end_at,
            DROP COLUMN IF EXISTS priority,
            DROP COLUMN IF EXISTS description,
            DROP COLUMN IF EXISTS title
        """
    )

    # Vessels
    op.execute("DROP INDEX IF EXISTS uq_vessels_company_hull_id;")
    op.execute("DROP INDEX IF EXISTS idx_vessels_company_customer;")
    for name in (
        "ck_vessels_engine_count",
        "ck_vessels_engine_hours",
        "ck_vessels_draft",
        "ck_vessels_beam",
        "ck_vessels_length",
        "ck_vessels_year",
        "fk_vessels_customer",
    ):
        op.execute(f"ALTER TABLE vessels DROP CONSTRAINT IF EXISTS {name};")
    op.execute("ALTER TABLE vessels ALTER COLUMN customer_id DROP NOT NULL;")
    op.execute(
        """
        ALTER TABLE vessels
            ADD CONSTRAINT vessels_customer_id_fkey
                FOREIGN KEY (customer_id) REFERENCES customers(id)
        """
    )
    op.execute(
        """
        ALTER TABLE vessels
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS slip_number,
            DROP COLUMN IF EXISTS storage_location,
            DROP COLUMN IF EXISTS draft_ft,
            DROP COLUMN IF EXISTS beam_ft,
            DROP COLUMN IF EXISTS engine_count,
            DROP COLUMN IF EXISTS engine_model,
            DROP COLUMN IF EXISTS engine_make
        """
    )

    # Customers
    op.execute("DROP INDEX IF EXISTS idx_customers_company_email;")
    op.execute("DROP INDEX IF EXISTS idx_customers_company_name;")
    op.execute("ALTER TABLE customers DROP CONSTRAINT IF EXISTS ck_customers_has_a_name;")
    op.execute(
        """
        ALTER TABLE customers
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS country,
            DROP COLUMN IF EXISTS company_name
        """
    )

    # Composite-FK targets
    op.execute("ALTER TABLE invoices  DROP CONSTRAINT IF EXISTS uq_invoices_company_id;")
    op.execute("ALTER TABLE jobs      DROP CONSTRAINT IF EXISTS uq_jobs_company_id;")
    op.execute("ALTER TABLE vessels   DROP CONSTRAINT IF EXISTS uq_vessels_company_id;")
    op.execute("ALTER TABLE customers DROP CONSTRAINT IF EXISTS uq_customers_company_id;")
    op.execute("ALTER TABLE users     DROP CONSTRAINT IF EXISTS uq_users_company_id;")

    op.execute("DROP TYPE IF EXISTS job_line_item_kind;")
    op.execute("DROP TYPE IF EXISTS job_priority;")
