"""Least privilege: app role gets read-only access to global reference tables.

`subscription_plans` is a platform-wide catalog and `alembic_version` is
migration bookkeeping; neither has RLS (no `company_id`). The initial GRANT
gave `harboriq_app` INSERT/UPDATE/DELETE on both. No request path writes
them as the app role — plans are seeded/managed by the service role and
migrations always run as the service role (`alembic/env.py`) — so a tenant
request path that could modify the catalog or the schema version is pure
unnecessary privilege. `SELECT` on `subscription_plans` is kept for billing
reads.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-22
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON subscription_plans FROM harboriq_app"
    )
    op.execute("REVOKE ALL ON alembic_version FROM harboriq_app")


def downgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version TO harboriq_app")
    op.execute("GRANT INSERT, UPDATE, DELETE ON subscription_plans TO harboriq_app")
