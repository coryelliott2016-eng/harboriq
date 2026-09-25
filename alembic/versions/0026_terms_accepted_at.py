"""Record Terms/Privacy consent server-side (Known Limitations L25).

Signup previously enforced Terms-of-Service / Privacy-Policy agreement only
in the signup UI; the API neither required nor recorded it, leaving no legal
evidence of consent. `users.terms_accepted_at` stores the server-side
timestamp captured when the signup API validated `agreed_to_terms: true`.

Nullable: pre-existing users (created before this migration) and staff
accounts created via owner/admin invite have no self-service consent event,
so NULL means "no recorded self-service consent", not "consent refused".

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "terms_accepted_at")
