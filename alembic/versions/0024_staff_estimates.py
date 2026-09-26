"""Staff-authored estimates: numeric quantities, line kinds, tax rate.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-22
"""
from pathlib import Path

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0024_staff_estimates.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_estimates_company_job")
    op.execute("DROP INDEX IF EXISTS ix_estimate_line_items_estimate_id")
    op.execute(
        """
        ALTER TABLE estimates
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS sent_at,
            DROP COLUMN IF EXISTS tax_rate
        """
    )
    op.execute(
        "ALTER TABLE estimate_line_items "
        "DROP CONSTRAINT IF EXISTS ck_estimate_line_items_kind_not_storage"
    )
    op.execute(
        """
        ALTER TABLE estimate_line_items
            DROP COLUMN IF EXISTS created_at,
            DROP COLUMN IF EXISTS position,
            DROP COLUMN IF EXISTS taxable,
            DROP COLUMN IF EXISTS kind,
            DROP COLUMN IF EXISTS line_total
        """
    )
    # Lossy by nature: fractional quantities round to the nearest whole unit.
    op.execute(
        """
        ALTER TABLE estimate_line_items
            ALTER COLUMN quantity TYPE INTEGER USING GREATEST(1, round(quantity))::integer
        """
    )
    op.execute(
        """
        ALTER TABLE estimate_line_items
            ADD COLUMN line_total NUMERIC(12,2)
                GENERATED ALWAYS AS (quantity * unit_price) STORED
        """
    )
