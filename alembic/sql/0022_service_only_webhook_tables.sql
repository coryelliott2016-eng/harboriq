-- ============================================================================
-- 0022 — Service-only access for cross-tenant webhook idempotency tables
-- ============================================================================
-- M-2 follow-up (Security Core Prompt v1.0 audit, 2026-08-05).
--
-- Full table-by-table RLS inventory confirmed every tenant-scoped table has
-- ENABLE + FORCE ROW LEVEL SECURITY and a tenant_isolation_* policy, with
-- two deliberate exceptions that predate this migration:
--
--   * stripe_processed_events  (0001_initial.sql)
--   * crypto_processed_events  (0020_crypto_payment_rail.sql)
--
-- Both are cross-tenant webhook-dedup ledgers written by the service role
-- BEFORE tenant context is established (the webhook resolves company_id
-- from the event payload). RLS is the wrong tool for them — a per-tenant
-- policy would either hide the row the service needs to look up by event
-- id, or would have to be so loose it buys nothing.
--
-- What WAS wrong: both tables inherited the default
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES ... TO harboriq_app
-- from 0001, so the RLS-enforced app role could still read every tenant's
-- webhook history (event ids, outcomes, linked company_ids) with a single
-- unscoped SELECT. That is a real cross-tenant information leak via the
-- wrong role, not via a missing policy.
--
-- Fix: revoke the app role entirely. Only harboriq_service (BYPASSRLS)
-- may touch these tables. Application request paths never need them;
-- webhook handlers already use the service engine.
-- ============================================================================

REVOKE ALL ON TABLE stripe_processed_events FROM harboriq_app;
REVOKE ALL ON TABLE crypto_processed_events FROM harboriq_app;

-- Defense in depth: even if a future migration re-grants via
-- ALL TABLES IN SCHEMA public, make the intent visible in pg_class
-- comments so the next auditor does not re-open the question.
COMMENT ON TABLE stripe_processed_events IS
    'Cross-tenant Stripe webhook idempotency ledger. SERVICE ROLE ONLY '
    '(harboriq_service). No RLS by design — tenant is resolved from the '
    'event payload before any tenant context exists. App role deliberately '
    'revoked in migration 0022.';

COMMENT ON TABLE crypto_processed_events IS
    'Cross-tenant crypto-processor webhook idempotency ledger. SERVICE '
    'ROLE ONLY (harboriq_service). No RLS by design — matches '
    'stripe_processed_events. App role deliberately revoked in migration 0022.';
