"""M-2 regression: every tenant-scoped table must enforce tenant isolation.

The 2026-08-05 security audit flagged uncertainty about RLS coverage on
tables introduced after the initial schema. A full inventory confirmed
that every table with a `company_id` column has ENABLE + FORCE ROW LEVEL
SECURITY and a policy — except two cross-tenant webhook idempotency
ledgers that are intentionally service-role-only:

  * stripe_processed_events
  * crypto_processed_events

Migration 0022 revokes the app role from those two tables entirely, so
the RLS-enforced request path cannot read cross-tenant webhook history
even without a policy.

This test locks that contract in place: a future migration that adds a
`company_id` column without RLS (or re-grants the app role on a
service-only table) fails CI.
"""
from __future__ import annotations

from sqlalchemy import text

# Cross-tenant webhook dedup ledgers. Written by harboriq_service before
# any tenant context exists; app role must have zero privileges.
SERVICE_ONLY_TABLES = frozenset(
    {
        "stripe_processed_events",
        "crypto_processed_events",
    }
)

# Truly global / non-tenant reference data (no company_id, no RLS expected).
GLOBAL_TABLES = frozenset(
    {
        "subscription_plans",
        "alembic_version",
    }
)


def test_every_company_id_table_has_rls_force_and_policy(service_db):
    rows = service_db.execute(
        text(
            """
            SELECT c.relname AS table_name,
                   c.relrowsecurity AS rls_enabled,
                   c.relforcerowsecurity AS rls_forced,
                   EXISTS (
                       SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid
                   ) AS has_policy
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind = 'r'
               AND EXISTS (
                   SELECT 1
                     FROM information_schema.columns col
                    WHERE col.table_schema = 'public'
                      AND col.table_name = c.relname
                      AND col.column_name = 'company_id'
               )
             ORDER BY c.relname
            """
        )
    ).mappings().all()

    assert rows, "expected at least one public table with company_id"

    gaps = []
    for row in rows:
        name = row["table_name"]
        if name in SERVICE_ONLY_TABLES:
            # Service-only tables are allowed to skip RLS; covered by the
            # privilege test below.
            continue
        if not row["rls_enabled"] or not row["rls_forced"] or not row["has_policy"]:
            gaps.append(
                f"{name}: rls={row['rls_enabled']} force={row['rls_forced']} "
                f"policy={row['has_policy']}"
            )

    assert not gaps, (
        "tenant-scoped tables missing ENABLE/FORCE RLS or a policy:\n  - "
        + "\n  - ".join(gaps)
    )


def test_service_only_webhook_tables_revoke_app_role(service_db, app_db):
    """harboriq_app must not be able to read cross-tenant webhook ledgers."""
    for table in sorted(SERVICE_ONLY_TABLES):
        # Confirm the table still exists (service role can see it).
        n = service_db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        assert n >= 0

        # App role must be denied. Postgres raises InsufficientPrivilege
        # (SQLSTATE 42501) on SELECT when REVOKE ALL is in effect.
        try:
            app_db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            app_db.rollback()
            raise AssertionError(
                f"harboriq_app was able to SELECT from {table}; expected REVOKE ALL"
            )
        except Exception as exc:  # noqa: BLE001 — SQLAlchemy wraps DBAPIError
            app_db.rollback()
            msg = str(exc).lower()
            assert (
                "permission denied" in msg
                or "insufficientprivilege" in msg
                or "42501" in msg
            ), f"unexpected error probing {table}: {exc!r}"


def test_no_unexpected_public_tables_without_tenant_or_global_mark(service_db):
    """Catch brand-new public tables that are neither tenant-scoped nor
    explicitly allowlisted as global/service-only — forces a conscious
    decision the next time someone adds a table.

    Tables without `company_id` are still fine if they have RLS enabled
    (e.g. estimate_line_items isolates via a join to estimates).
    """
    rows = service_db.execute(
        text(
            """
            SELECT c.relname AS table_name,
                   c.relrowsecurity AS rls_enabled,
                   EXISTS (
                       SELECT 1
                         FROM information_schema.columns col
                        WHERE col.table_schema = 'public'
                          AND col.table_name = c.relname
                          AND col.column_name = 'company_id'
                   ) AS has_company_id
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind = 'r'
             ORDER BY c.relname
            """
        )
    ).mappings().all()

    unexpected = []
    for row in rows:
        name = row["table_name"]
        if row["has_company_id"] or row["rls_enabled"]:
            continue
        if name in GLOBAL_TABLES or name in SERVICE_ONLY_TABLES:
            continue
        unexpected.append(name)

    assert not unexpected, (
        "public tables with neither company_id, RLS, nor an explicit global/"
        "service-only allowlist — add RLS, or extend GLOBAL_TABLES/"
        f"SERVICE_ONLY_TABLES in this test with a justification: {unexpected}"
    )
