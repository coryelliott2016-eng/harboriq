-- HarborIQ v2 — Accounting & Reporting (Phase 14).
-- Executed verbatim by Alembic migration 0013_accounting_reports.
--
-- ============================================================================
-- USERS.HOURLY_RATE — the missing pay-rate field labor-cost reporting needs
-- ============================================================================
-- No pay-rate field exists anywhere in the schema prior to this migration.
-- The P&L report (GET /reports/pnl) needs to turn a technician's
-- `job_time_entries` duration into a real dollar labor cost, and the honest
-- move when that input doesn't exist yet is to add it -- nullable, so every
-- technician seeded before this phase (and any created after it without an
-- admin filling one in) has an explicit "no rate set" state the report can
-- surface as "labor cost unavailable," never silently coerced to 0. A CHECK
-- constraint mirrors the non-negative-money convention already used for
-- `purchase_order_line_items.unit_cost` etc. elsewhere in this schema.
ALTER TABLE users
    ADD COLUMN hourly_rate NUMERIC(12, 2);

ALTER TABLE users
    ADD CONSTRAINT ck_users_hourly_rate_gte0 CHECK (hourly_rate IS NULL OR hourly_rate >= 0);
