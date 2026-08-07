-- Phase 18 — Crypto Payment Rail (MVP).
--
-- HarborIQ never takes custody of a customer's on-chain assets.  This table
-- records a payment request and its licensed-processor webhook outcome; the
-- provider (initially Stripe's stablecoin/crypto Checkout support) remains
-- responsible for checkout, exchange, settlement, and compliance.
--
-- The invoice FK is composite so a crypto-payment row can never point across
-- tenants even though PostgreSQL FK checks are not themselves filtered by
-- RLS.  The RLS/grant shape intentionally follows refunds (0007) exactly.

CREATE TYPE crypto_payment_status AS ENUM ('pending', 'confirmed', 'failed', 'expired');

CREATE TABLE crypto_payments (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id         UUID NOT NULL REFERENCES companies(id),
    invoice_id         UUID NOT NULL,
    provider           TEXT NOT NULL,
    provider_reference TEXT,
    currency           TEXT NOT NULL,
    amount_requested   NUMERIC(12,2) NOT NULL CHECK (amount_requested > 0),
    status             crypto_payment_status NOT NULL DEFAULT 'pending',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at       TIMESTAMPTZ,
    raw_metadata       JSONB,
    CONSTRAINT fk_crypto_payments_invoice
        FOREIGN KEY (company_id, invoice_id)
        REFERENCES invoices (company_id, id)
);

CREATE INDEX idx_crypto_payments_company_invoice
    ON crypto_payments(company_id, invoice_id);
CREATE UNIQUE INDEX uq_crypto_payments_provider_reference
    ON crypto_payments(provider, provider_reference)
    WHERE provider_reference IS NOT NULL;

ALTER TABLE crypto_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE crypto_payments FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_crypto_payments ON crypto_payments
    USING (company_id::text = current_setting('app.current_company_id', true));

-- Cross-tenant, service-role webhook deduplication.  This table intentionally
-- has no RLS policy, matching stripe_processed_events from migration 0001:
-- the public webhook resolves the tenant before it enters tenant context.
CREATE TABLE crypto_processed_events (
    event_id       TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    company_id     UUID REFERENCES companies(id),
    resource_id    TEXT,
    http_status    INTEGER NOT NULL,
    outcome        TEXT NOT NULL,
    processed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON crypto_payments TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crypto_payments TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON crypto_processed_events TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crypto_processed_events TO harboriq_service;
