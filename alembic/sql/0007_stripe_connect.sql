-- HarborIQ v2 — Stripe Connect, refunds, dunning cadence (Phase 8).
-- Executed verbatim by Alembic migration 0007_stripe_connect.
--
-- Three independent additions, grouped into one migration because they are
-- all part of Phase 8 and touch small, non-overlapping pieces of schema:
--
--   1. `companies.stripe_connect_account_id` — set once a tenant completes
--      Stripe Connect Standard onboarding (see app/services/stripe_billing.py
--      and app/api/v1/routes/billing.py). Nullable and unpopulated for every
--      existing tenant; `app.services.invoices`/`stripe_billing` fall back to
--      today's single-platform-account behavior whenever it is NULL, so this
--      column being empty is a normal, fully-supported state, not a
--      migration hazard. Distinct from the pre-existing (and, it turns out,
--      never wired up) `companies.stripe_account_id` column from migration
--      0001 — that column predates this phase and nothing in the codebase
--      reads or writes it; it is left untouched rather than repurposed, to
--      avoid silently changing the meaning of a column that might already
--      hold operator-entered data in some deployment.
--   2. `refunds` — one row per Stripe refund (full or partial) applied to an
--      invoice. `payments` (0001) records money coming IN; refunds records
--      money going back OUT, and deliberately is not just another `payments`
--      row with a negative amount — a refund references the invoice (not
--      necessarily a specific payment row, since Stripe refunds target a
--      PaymentIntent/charge, and an invoice may have accumulated amount_paid
--      across more than one webhook delivery), and needs its own
--      stripe_refund_id for idempotency/audit, which `payments` has no slot
--      for today.
--   3. `invoices.last_reminder_sent_at` — dunning cadence tracking (see
--      app/jobs/dunning_sweep.py). Nullable; NULL means "never reminded yet."
--
-- Tenant-safety follows the exact pattern 0003/0004 established: RLS policy
-- + FORCE ROW LEVEL SECURITY + explicit grants to both roles (0001's
-- `ALTER DEFAULT PRIVILEGES` only ever covered harboriq_app for tables
-- created after 0001, and never covered harboriq_service at all — every
-- migration since 0003 has granted new tables to both roles by hand).

-- ============================================================================
-- COMPANIES — Stripe Connect account id
-- ============================================================================
ALTER TABLE companies ADD COLUMN stripe_connect_account_id TEXT;

-- ============================================================================
-- INVOICES — dunning cadence tracking
-- ============================================================================
ALTER TABLE invoices ADD COLUMN last_reminder_sent_at TIMESTAMPTZ;

-- ============================================================================
-- REFUNDS
-- ============================================================================
CREATE TABLE refunds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    invoice_id      UUID NOT NULL,
    amount          NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    reason          TEXT,
    stripe_refund_id TEXT,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tenant-safe composite FK to invoices, same discipline as every other
-- invoice-referencing table since 0004.
ALTER TABLE refunds
    ADD CONSTRAINT fk_refunds_invoice
        FOREIGN KEY (company_id, invoice_id)
        REFERENCES invoices (company_id, id);

CREATE INDEX idx_refunds_company_invoice ON refunds(company_id, invoice_id);
CREATE INDEX idx_refunds_company_created ON refunds(company_id, created_at DESC);

ALTER TABLE refunds ENABLE ROW LEVEL SECURITY;
ALTER TABLE refunds FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_refunds ON refunds
    USING (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON refunds TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON refunds TO harboriq_service;

-- Reporting: AR aging groups outstanding balances by customer and due date.
CREATE INDEX idx_invoices_company_due_date ON invoices(company_id, due_date)
    WHERE balance_due > 0;
