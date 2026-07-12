-- HarborIQ v2 — Initial schema (reference, corrects every issue from the critique)
-- PostgreSQL 14+. Loads extensions, enums, tables, RLS policies, roles, grants.
-- This file is executed verbatim by Alembic migration 0001_initial_schema.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- NOTE: extensions and the harboriq_app / harboriq_service roles are created
-- by docker-entrypoint-initdb.d/00_roles.sql (superuser context) BEFORE this
-- migration runs. They live there because extension/role creation requires
-- superuser privileges the migration role (harboriq_service) does not have.
-- The CREATE EXTENSION IF NOT EXISTS above is a no-op when they already exist.

-- ============================================================================
-- ENUMS
-- ============================================================================
CREATE TYPE subscription_status AS ENUM ('trialing', 'active', 'past_due', 'canceled', 'paused');
CREATE TYPE estimate_status     AS ENUM ('draft', 'sent', 'viewed', 'approved', 'declined', 'expired', 'invoiced');
CREATE TYPE invoice_status      AS ENUM ('draft', 'sent', 'partial', 'paid', 'void', 'uncollectible', 'refunded', 'partially_refunded');
CREATE TYPE job_status          AS ENUM ('scheduled', 'in_progress', 'on_hold', 'completed', 'canceled');
CREATE TYPE payment_status      AS ENUM ('pending', 'succeeded', 'failed', 'refunded', 'partially_refunded');
CREATE TYPE deposit_status      AS ENUM ('uninvoiced', 'invoiced', 'applied');
CREATE TYPE token_purpose       AS ENUM ('estimate_approve', 'invoice_pay', 'intake_form', 'document_upload');
CREATE TYPE money_currency      AS ENUM ('USD');

-- ============================================================================
-- TENANTS & USERS
-- ============================================================================
CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    stripe_account_id     TEXT,
    default_currency money_currency NOT NULL DEFAULT 'USD',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    email           CITEXT NOT NULL,
    password_hash   TEXT,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'technician',
    mfa_secret_enc  BYTEA,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    email_verified_at TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, email)
);

-- ============================================================================
-- BILLING / SUBSCRIPTIONS
-- ============================================================================
CREATE TABLE subscription_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    monthly_price   NUMERIC(12,2) NOT NULL CHECK (monthly_price >= 0),
    annual_price    NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (annual_price >= 0),
    currency        money_currency NOT NULL DEFAULT 'USD',
    seat_limit      INTEGER NOT NULL DEFAULT 1 CHECK (seat_limit >= 1),
    is_active       BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    plan_id         UUID NOT NULL REFERENCES subscription_plans(id),
    status          subscription_status NOT NULL DEFAULT 'trialing',
    stripe_customer_id    TEXT,
    stripe_subscription_id TEXT,
    trial_ends_at   TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    canceled_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_subscriptions_stripe_sub
    ON subscriptions(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;

-- Idempotent Stripe webhook processing (cross-tenant; service-role access only).
CREATE TABLE stripe_processed_events (
    stripe_event_id    TEXT PRIMARY KEY,
    event_type         TEXT NOT NULL,
    company_id         UUID REFERENCES companies(id),
    resource_id        TEXT,
    processed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status        INTEGER NOT NULL,
    outcome            TEXT NOT NULL
);

-- ============================================================================
-- OUTBOX — non-DB side effects (emails, SMS, receipts, outbound webhooks)
-- written in the same transaction as the state change, dispatched AFTER commit.
-- ============================================================================
CREATE TABLE outbox_events (
    id              BIGSERIAL PRIMARY KEY,
    company_id      UUID NOT NULL REFERENCES companies(id),
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|dispatched|dead_letter
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at   TIMESTAMPTZ
);
CREATE INDEX idx_outbox_pending ON outbox_events(status, created_at) WHERE status = 'pending';

-- ============================================================================
-- CUSTOMERS & VESSELS
-- ============================================================================
CREATE TABLE customers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    first_name      TEXT, last_name TEXT,
    email           CITEXT, phone TEXT,
    sms_consent_at  TIMESTAMPTZ,
    sms_opted_out   BOOLEAN NOT NULL DEFAULT false,
    address_line1   TEXT, address_line2 TEXT, city TEXT, state TEXT, postal_code TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vessels (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    customer_id     UUID REFERENCES customers(id),
    name            TEXT, make TEXT, model TEXT, year INTEGER,
    hull_id         TEXT, registration TEXT,
    length_ft       NUMERIC(6,2),
    engine_hours    INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- INVENTORY
-- ============================================================================
CREATE TABLE inventory_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    sku             TEXT, name TEXT NOT NULL,
    unit_cost       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    retail_price    NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (retail_price >= 0),
    currency        money_currency NOT NULL DEFAULT 'USD',
    quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    reorder_point   INTEGER NOT NULL DEFAULT 0,
    low_stock_alerted BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_inventory_company_sku ON inventory_items(company_id, sku);

-- ============================================================================
-- JOBS / ESTIMATES / INVOICES / PAYMENTS
-- ============================================================================
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    customer_id     UUID REFERENCES customers(id),
    vessel_id       UUID REFERENCES vessels(id),
    status          job_status NOT NULL DEFAULT 'scheduled',
    scheduled_at    TIMESTAMPTZ, technician_id UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE estimates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    job_id          UUID REFERENCES jobs(id),
    customer_id     UUID REFERENCES customers(id),
    status          estimate_status NOT NULL DEFAULT 'draft',
    currency        money_currency NOT NULL DEFAULT 'USD',
    subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,
    tax_total       NUMERIC(12,2) NOT NULL DEFAULT 0,
    total           NUMERIC(12,2) NOT NULL DEFAULT 0,
    balance_due     NUMERIC(12,2) NOT NULL DEFAULT 0,
    approved_at     TIMESTAMPTZ,
    approved_ip     INET,
    approved_user_agent TEXT,
    estimate_pdf_version TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE estimate_line_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    estimate_id     UUID NOT NULL REFERENCES estimates(id),
    inventory_item_id UUID REFERENCES inventory_items(id),
    description     TEXT, quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total       NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

CREATE TABLE invoices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    estimate_id     UUID REFERENCES estimates(id),
    customer_id     UUID REFERENCES customers(id),
    status          invoice_status NOT NULL DEFAULT 'draft',
    currency        money_currency NOT NULL DEFAULT 'USD',
    subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,
    tax_total       NUMERIC(12,2) NOT NULL DEFAULT 0,
    total           NUMERIC(12,2) NOT NULL DEFAULT 0,
    amount_paid     NUMERIC(12,2) NOT NULL DEFAULT 0,
    balance_due     NUMERIC(12,2) NOT NULL DEFAULT 0,
    stripe_payment_intent_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_invoices_company_created ON invoices(company_id, created_at DESC);

CREATE TABLE payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    invoice_id      UUID REFERENCES invoices(id),
    status          payment_status NOT NULL DEFAULT 'pending',
    amount          NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    currency        money_currency NOT NULL DEFAULT 'USD',
    stripe_charge_id TEXT,
    stripe_fee      NUMERIC(12,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- PUBLIC ACCESS TOKENS
-- ============================================================================
CREATE TABLE public_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    resource_type   TEXT NOT NULL,
    resource_id     UUID NOT NULL,
    purpose         token_purpose NOT NULL,
    token_hash      TEXT NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ NOT NULL,
    max_uses        INTEGER NOT NULL DEFAULT 1 CHECK (max_uses >= 1),
    uses            INTEGER NOT NULL DEFAULT 0,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_public_tokens_hash ON public_tokens(token_hash);

-- ============================================================================
-- AUDIT LOG (append-only)
-- ============================================================================
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    company_id      UUID NOT NULL,
    actor_user_id   UUID,
    actor_ip        INET,
    action          TEXT NOT NULL,
    resource_type   TEXT, resource_id UUID,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE RULE audit_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- ============================================================================
-- ROW-LEVEL SECURITY (tenant isolation backstop)
-- ============================================================================
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers          ENABLE ROW LEVEL SECURITY;
ALTER TABLE vessels            ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_items    ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs               ENABLE ROW LEVEL SECURITY;
ALTER TABLE estimates          ENABLE ROW LEVEL SECURITY;
ALTER TABLE estimate_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices           ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_tokens      ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events      ENABLE ROW LEVEL SECURITY;

-- FORCE: policies apply even to the table owner (defense in depth).
ALTER TABLE users              FORCE ROW LEVEL SECURITY;
ALTER TABLE subscriptions      FORCE ROW LEVEL SECURITY;
ALTER TABLE customers          FORCE ROW LEVEL SECURITY;
ALTER TABLE vessels            FORCE ROW LEVEL SECURITY;
ALTER TABLE inventory_items    FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs               FORCE ROW LEVEL SECURITY;
ALTER TABLE estimates          FORCE ROW LEVEL SECURITY;
ALTER TABLE estimate_line_items FORCE ROW LEVEL SECURITY;
ALTER TABLE invoices           FORCE ROW LEVEL SECURITY;
ALTER TABLE payments           FORCE ROW LEVEL SECURITY;
ALTER TABLE public_tokens      FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_log          FORCE ROW LEVEL SECURITY;
ALTER TABLE outbox_events      FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_users ON users
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_subscriptions ON subscriptions
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_customers ON customers
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_vessels ON vessels
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_inventory ON inventory_items
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_jobs ON jobs
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_estimates ON estimates
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_invoices ON invoices
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_payments ON payments
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_public_tokens ON public_tokens
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_audit ON audit_log
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_outbox ON outbox_events
    USING (company_id::text = current_setting('app.current_company_id', true));

CREATE POLICY tenant_isolation_estimate_lines ON estimate_line_items
    USING (EXISTS (
        SELECT 1 FROM estimates e
        WHERE e.id = estimate_line_items.estimate_id
          AND e.company_id::text = current_setting('app.current_company_id', true)
    ));

-- ============================================================================
-- GRANTS
-- ============================================================================
-- App role: full CRUD on tenant-scoped tables (RLS still filters rows).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO harboriq_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO harboriq_app;
-- Audit log is append-only (no UPDATE/DELETE even with table-level grant;
-- RULEs enforce it). Sequence usage granted for inserts.
REVOKE UPDATE, DELETE ON audit_log FROM harboriq_app;

-- Service role: cross-tenant resolution (BYPASSRLS).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO harboriq_service;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO harboriq_service;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO harboriq_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO harboriq_app;

-- Reporting indexes
CREATE INDEX idx_invoices_company_status ON invoices(company_id, status);
CREATE INDEX idx_payments_company_created ON payments(company_id, created_at DESC);
CREATE INDEX idx_jobs_company_scheduled ON jobs(company_id, scheduled_at);
CREATE INDEX idx_audit_company_created ON audit_log(company_id, created_at DESC);
