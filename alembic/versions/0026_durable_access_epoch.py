"""Persist access-token revocation generations with each user.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-18
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN access_epoch INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN access_epoch")
