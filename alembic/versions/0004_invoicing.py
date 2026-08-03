"""Invoicing & Stripe payment collection — loads the checked-in SQL verbatim.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-02
"""
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0004_invoicing.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_job_line_items_invoice;")

    op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS fk_payments_invoice;")
    op.execute(
        """
        ALTER TABLE payments
            ADD CONSTRAINT payments_invoice_id_fkey
                FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        """
    )

    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS ck_invoices_amount_paid_lte_total;")
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS ck_invoices_tax_rate;")
    op.execute("DROP TRIGGER IF EXISTS trg_invoices_updated_at ON invoices;")
    op.execute("DROP FUNCTION IF EXISTS set_invoices_updated_at();")
    op.execute(
        """
        ALTER TABLE invoices
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS stripe_checkout_session_id,
            DROP COLUMN IF EXISTS voided_at,
            DROP COLUMN IF EXISTS paid_at,
            DROP COLUMN IF EXISTS sent_at,
            DROP COLUMN IF EXISTS due_date,
            DROP COLUMN IF EXISTS tax_rate
        """
    )
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS fk_invoices_customer;")
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS fk_invoices_estimate;")
    op.execute(
        """
        ALTER TABLE invoices
            ADD CONSTRAINT invoices_estimate_id_fkey
                FOREIGN KEY (estimate_id) REFERENCES estimates(id),
            ADD CONSTRAINT invoices_customer_id_fkey
                FOREIGN KEY (customer_id) REFERENCES customers(id)
        """
    )

    op.execute("ALTER TABLE estimates DROP CONSTRAINT IF EXISTS fk_estimates_customer;")
    op.execute("ALTER TABLE estimates DROP CONSTRAINT IF EXISTS fk_estimates_job;")
    op.execute(
        """
        ALTER TABLE estimates
            ADD CONSTRAINT estimates_job_id_fkey
                FOREIGN KEY (job_id) REFERENCES jobs(id),
            ADD CONSTRAINT estimates_customer_id_fkey
                FOREIGN KEY (customer_id) REFERENCES customers(id)
        """
    )
    op.execute("ALTER TABLE estimates DROP CONSTRAINT IF EXISTS uq_estimates_company_id;")
