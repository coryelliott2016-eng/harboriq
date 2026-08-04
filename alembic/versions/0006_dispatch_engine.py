"""AI dispatch engine: skills, coordinates, cached job score — loads the
checked-in SQL verbatim.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-04
"""
from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0006_dispatch_engine.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE jobs
            DROP COLUMN IF EXISTS dispatch_scored_at,
            DROP COLUMN IF EXISTS dispatch_score_breakdown,
            DROP COLUMN IF EXISTS dispatch_score,
            DROP COLUMN IF EXISTS required_skills
        """
    )
    op.execute("ALTER TABLE customers DROP CONSTRAINT IF EXISTS ck_customers_latlng_pair;")
    op.execute(
        """
        ALTER TABLE customers
            DROP COLUMN IF EXISTS longitude,
            DROP COLUMN IF EXISTS latitude
        """
    )
    op.execute("ALTER TABLE companies DROP CONSTRAINT IF EXISTS ck_companies_latlng_pair;")
    op.execute(
        """
        ALTER TABLE companies
            DROP COLUMN IF EXISTS longitude,
            DROP COLUMN IF EXISTS latitude
        """
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_home_latlng_pair;")
    op.execute(
        """
        ALTER TABLE users
            DROP COLUMN IF EXISTS home_longitude,
            DROP COLUMN IF EXISTS home_latitude,
            DROP COLUMN IF EXISTS skills
        """
    )
