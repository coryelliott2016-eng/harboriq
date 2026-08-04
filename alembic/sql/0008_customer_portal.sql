-- HarborIQ v2 — Customer self-service portal (Phase 9).
-- Executed verbatim by Alembic migration 0008_customer_portal.
--
-- Portal access model (see README "Customer portal" for the full write-up):
-- Option A from the phase spec was chosen — a longer-lived, revocable
-- `public_tokens` row (`resource_type = 'customer'`, new purpose `'portal'`,
-- 90-day TTL, effectively-unlimited `max_uses` within that window) rather
-- than a real customer login (email/password or OTP). This is a pure
-- extension of the ENUM the exact same way migration 0005 added
-- 'user_invite' — no new token table, no parallel auth mechanism. The
-- customer's magic link resolves the same way every existing public token
-- does: a service-role (BYPASSRLS) global lookup by hashed token, THEN
-- `tenant_context` for everything else, so RLS is never bypassed for the
-- customer's own data reads. Trade-off: a customer who loses the email
-- containing their link has no self-service "log back in" until staff
-- re-sends it (`POST /customers/{id}/portal-invite`) or the shop emails one
-- automatically after the customer's first invoice/job — see README's
-- deferred-items list for why a full password/account system remains out of
-- scope for this phase.
--
-- New capability, not just a new token purpose: customer<->staff messaging.
-- `messages` is a new table (this migration's only new table) — one row per
-- message, threaded by `job_id` (nullable: a message can be general or
-- job-specific), tagged `sender_type` so the UI can tell customer-authored
-- from staff-authored without joining `users`. Tenant-isolated by RLS with
-- the exact same discipline as every table since 0003: FORCE ROW LEVEL
-- SECURITY + an explicit policy + explicit grants to both roles (0001's
-- `ALTER DEFAULT PRIVILEGES` only ever covered harboriq_app for tables
-- created after 0001, and never covered harboriq_service).
--
-- Portal reads (vessels/jobs/invoices/estimates) need NO new tables — they
-- are plain, RLS-scoped SELECTs against tables that already exist
-- (`customers`, `vessels`, `jobs`, `invoices`, `estimates`), further scoped
-- in application code to the token's own `customer_id` so Customer A can
-- never see Customer B's rows even within the same tenant (RLS alone only
-- guarantees company-level isolation, not customer-level isolation within a
-- company — that narrower scoping is the portal service layer's job, see
-- `app/services/portal.py`).

-- ============================================================================
-- PUBLIC_TOKENS — new 'portal' purpose, extending the existing ENUM
-- ============================================================================
-- Same idempotent/forward-only pattern as 0005_auth_hardening.sql's
-- 'user_invite' addition: PostgreSQL 12+ allows ADD VALUE inside a
-- transaction as long as the new value is not used in that same
-- transaction (it is not — this migration never inserts a 'portal' row).
ALTER TYPE token_purpose ADD VALUE IF NOT EXISTS 'portal';

-- ============================================================================
-- MESSAGES — customer <-> staff threads
-- ============================================================================
CREATE TYPE message_sender_type AS ENUM ('customer', 'staff');

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    customer_id     UUID NOT NULL,
    job_id          UUID,
    sender_type     message_sender_type NOT NULL,
    -- Populated only for staff-authored messages; NULL for a customer
    -- message (a customer has no `users` row -- that is the whole point of
    -- the magic-link portal model above).
    sender_user_id  UUID REFERENCES users(id),
    body            TEXT NOT NULL CHECK (BTRIM(body) <> ''),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at         TIMESTAMPTZ
);

-- Tenant-safe composite FKs, same discipline as every customer/job-
-- referencing table since 0003 -- a cross-tenant reference is made
-- unrepresentable rather than merely "checked for" in application code.
ALTER TABLE messages
    ADD CONSTRAINT fk_messages_customer
        FOREIGN KEY (company_id, customer_id)
        REFERENCES customers (company_id, id);

ALTER TABLE messages
    ADD CONSTRAINT fk_messages_job
        FOREIGN KEY (company_id, job_id)
        REFERENCES jobs (company_id, id);

-- A staff-authored message must record who sent it; a customer message
-- never has a `users` row to point at.
ALTER TABLE messages
    ADD CONSTRAINT ck_messages_staff_has_sender
        CHECK (sender_type <> 'staff' OR sender_user_id IS NOT NULL);

CREATE INDEX idx_messages_company_customer ON messages(company_id, customer_id, created_at);
CREATE INDEX idx_messages_company_job ON messages(company_id, job_id, created_at)
    WHERE job_id IS NOT NULL;
-- "Unread customer messages" is the staff inbox's main query -- messages the
-- customer sent that no staff member has read yet.
CREATE INDEX idx_messages_company_unread ON messages(company_id, created_at)
    WHERE read_at IS NULL AND sender_type = 'customer';

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_messages ON messages
    USING (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON messages TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON messages TO harboriq_service;
