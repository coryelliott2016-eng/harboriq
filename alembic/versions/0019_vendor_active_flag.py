"""Vendor deactivate/archive (Phase 17, Area F): adds vendors.is_active so a
vendor a business no longer orders from can be hidden from the default
vendor list / new-PO picker without breaking historical purchase orders
that still reference it -- loads the checked-in SQL verbatim.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0019_vendor_active_flag.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_vendors_company_active")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS is_active")
