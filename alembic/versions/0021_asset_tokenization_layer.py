"""Asset tokenization layer (Phase 19): draft registration only.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-07
"""
from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0021_asset_tokenization_layer.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS token_ledger_entries")
    op.execute("DROP TABLE IF EXISTS asset_tokens")
    op.execute("DROP TYPE IF EXISTS asset_token_type")
