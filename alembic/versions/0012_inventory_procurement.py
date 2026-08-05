"""Inventory, Parts & Vendor Integration (Phase 13): per-tenant unique SKU
index on inventory_items, vendors, purchase_orders + line items, and
inventory_items.default_vendor_id -- loads the checked-in SQL verbatim.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-05
"""
from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0012_inventory_procurement.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purchase_order_line_items")
    op.execute("DROP TABLE IF EXISTS purchase_orders")
    op.execute("DROP TYPE IF EXISTS purchase_order_status")
    op.execute("ALTER TABLE inventory_items DROP COLUMN IF EXISTS default_vendor_id")
    op.execute("DROP TABLE IF EXISTS vendors")
    op.execute("DROP INDEX IF EXISTS uq_inventory_items_company_sku")
