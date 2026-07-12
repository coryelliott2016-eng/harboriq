"""Initial schema — loads the checked-in SQL verbatim.

Revision ID: 0001
Revises:
Create Date: 2026-07-10
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    sql = SQL_FILE.read_text()
    op.execute(sql)


def downgrade() -> None:
    # Drop in dependency-safe order. Schemas rarely roll back to empty in prod,
    # but the reverse path is provided for staging rehearsal.
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS public_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS payments CASCADE;")
    op.execute("DROP TABLE IF EXISTS invoices CASCADE;")
    op.execute("DROP TABLE IF EXISTS estimate_line_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS estimates CASCADE;")
    op.execute("DROP TABLE IF EXISTS jobs CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS vessels CASCADE;")
    op.execute("DROP TABLE IF EXISTS customers CASCADE;")
    op.execute("DROP TABLE IF EXISTS stripe_processed_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS subscriptions CASCADE;")
    op.execute("DROP TABLE IF EXISTS subscription_plans CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    op.execute("DROP TABLE IF EXISTS companies CASCADE;")
    op.execute("DROP TYPE IF EXISTS subscription_status;")
    op.execute("DROP TYPE IF EXISTS estimate_status;")
    op.execute("DROP TYPE IF EXISTS invoice_status;")
    op.execute("DROP TYPE IF EXISTS job_status;")
    op.execute("DROP TYPE IF EXISTS payment_status;")
    op.execute("DROP TYPE IF EXISTS deposit_status;")
    op.execute("DROP TYPE IF EXISTS token_purpose;")
    op.execute("DROP TYPE IF EXISTS money_currency;")
