-- HarborIQ v2 — Invoicing & Stripe payment collection.
-- Executed verbatim by Alembic migration 0004_invoicing.
--
-- 0001 created skeleton `estimates`, `invoices` and `payments` tables with
-- plain (tenant-blind) foreign keys, and 0003 explained why that is a hole: an
-- internal FK-check query is NOT subject to RLS, so tenant A could point an
-- invoice at tenant B's customer id and the constraint would happily accept
-- it. This migration closes that hole for the billing tables the same way
-- 0003 closed it for customers/vessels/jobs — composite `(company_id, <id>)`
-- foreign keys — and adds the columns/constraint the invoicing service needs
-- to actually run a draft -> sent -> paid lifecycle.
--
-- job_line_items.invoice_id already got its composite FK in 0003
-- (fk_job_line_items_invoice, "reserved for the invoicing phase") — this is
-- simply the first migration where anything actually writes the column.

-- ============================================================================
-- COMPOSITE-KEY TARGETS
-- ============================================================================
-- estimates never got its own (company_id, id) uniqueness (invoices did, in
-- 0003, "reserved for the invoicing phase"). Add the missing one now so both
-- estimates and invoices are legal composite-FK targets.
ALTER TABLE estimates ADD CONSTRAINT uq_estimates_company_id UNIQUE (company_id, id);

-- ============================================================================
-- ESTIMATES — rewrite job_id / customer_id as tenant-safe composite FKs
-- ============================================================================
ALTER TABLE estimates DROP CONSTRAINT IF EXISTS estimates_job_id_fkey;
ALTER TABLE estimates DROP CONSTRAINT IF EXISTS estimates_customer_id_fkey;

ALTER TABLE estimates
    ADD CONSTRAINT fk_estimates_job
        FOREIGN KEY (company_id, job_id)
        REFERENCES jobs (company_id, id),
    ADD CONSTRAINT fk_estimates_customer
        FOREIGN KEY (company_id, customer_id)
        REFERENCES customers (company_id, id);

-- ============================================================================
-- INVOICES — rewrite estimate_id / customer_id as tenant-safe composite FKs,
-- add the lifecycle columns the sent/paid/void state machine needs.
-- ============================================================================
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_estimate_id_fkey;
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_customer_id_fkey;

ALTER TABLE invoices
    ADD CONSTRAINT fk_invoices_estimate
        FOREIGN KEY (company_id, estimate_id)
        REFERENCES estimates (company_id, id),
    ADD CONSTRAINT fk_invoices_customer
        FOREIGN KEY (company_id, customer_id)
        REFERENCES customers (company_id, id);

-- `Invoice` has declared a `TimestampMixin.updated_at` at the ORM level since
-- 0001, but 0001's raw DDL never actually created the column (same latent gap
-- exists on `estimates`, left untouched -- out of scope here). It was
-- harmless while invoices were create-once-and-done; now that a real
-- draft -> sent -> paid/void lifecycle mutates the row repeatedly, callers
-- (and `InvoiceOut`) need a trustworthy "last touched" timestamp, so we add
-- it for real here rather than propagate the gap further.
ALTER TABLE invoices
    ADD COLUMN tax_rate    NUMERIC(5,4) NOT NULL DEFAULT 0,
    ADD COLUMN due_date    TIMESTAMPTZ,
    ADD COLUMN sent_at     TIMESTAMPTZ,
    ADD COLUMN paid_at     TIMESTAMPTZ,
    ADD COLUMN voided_at   TIMESTAMPTZ,
    ADD COLUMN stripe_checkout_session_id TEXT,
    ADD COLUMN updated_at  TIMESTAMPTZ NOT NULL DEFAULT now();

-- Keep it current on every UPDATE without relying on every service call
-- remembering to set it by hand.
CREATE OR REPLACE FUNCTION set_invoices_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_invoices_updated_at
    BEFORE UPDATE ON invoices
    FOR EACH ROW
    EXECUTE FUNCTION set_invoices_updated_at();

ALTER TABLE invoices
    ADD CONSTRAINT ck_invoices_tax_rate CHECK (tax_rate >= 0 AND tax_rate <= 1),
    -- amount_paid tracks partial payments; it must never exceed what is owed.
    -- balance_due stays app-maintained (unlike job_line_items.line_total,
    -- it changes repeatedly over the invoice's life as payments land, so a
    -- single GENERATED expression cannot express it).
    ADD CONSTRAINT ck_invoices_amount_paid_lte_total CHECK (amount_paid <= total);

-- ============================================================================
-- PAYMENTS — rewrite invoice_id as a tenant-safe composite FK
-- ============================================================================
ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_invoice_id_fkey;
ALTER TABLE payments
    ADD CONSTRAINT fk_payments_invoice
        FOREIGN KEY (company_id, invoice_id)
        REFERENCES invoices (company_id, id);

-- ============================================================================
-- JOB LINE ITEMS — the invoicing phase's input gets an aggregation index
-- ============================================================================
-- fk_job_line_items_invoice (composite, nullable) already exists from 0003.
-- Add the index for "what is on this invoice" — voiding needs to free every
-- line back to uninvoiced, and the invoice-detail view needs to list them.
CREATE INDEX idx_job_line_items_invoice
    ON job_line_items (company_id, invoice_id) WHERE invoice_id IS NOT NULL;
