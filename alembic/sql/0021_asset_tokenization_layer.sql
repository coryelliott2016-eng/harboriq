-- Phase 19 — Asset Tokenization Layer (Exploratory).
--
-- This is deliberately a draft-registration record only, pending outside
-- securities-counsel review. The database, not just application policy,
-- prevents a token record from ever leaving draft in this phase. No unit,
-- ownership, transfer, trading, or valuation-allocation data exists here.
--
-- The composite FKs ensure neither a vessel reference nor a ledger entry can
-- cross tenants even though PostgreSQL FK checks are not filtered by RLS. The
-- RLS/grant shape intentionally follows crypto_payments (0020) exactly.

CREATE TYPE asset_token_type AS ENUM ('vessel', 'slip', 'equipment', 'receivable');

CREATE TABLE asset_tokens (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id         UUID NOT NULL REFERENCES companies(id),
    asset_type         asset_token_type NOT NULL,
    vessel_id          UUID,
    source_description TEXT NOT NULL,
    estimated_value    NUMERIC(12,2),
    notes              TEXT,
    status             TEXT NOT NULL DEFAULT 'draft',
    created_by         UUID NOT NULL REFERENCES users(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_asset_tokens_status_draft CHECK (status = 'draft'),
    CONSTRAINT fk_asset_tokens_vessel
        FOREIGN KEY (company_id, vessel_id)
        REFERENCES vessels (company_id, id),
    CONSTRAINT uq_asset_tokens_company_id UNIQUE (company_id, id)
);

CREATE INDEX idx_asset_tokens_company_created
    ON asset_tokens(company_id, created_at DESC);
CREATE INDEX idx_asset_tokens_company_vessel
    ON asset_tokens(company_id, vessel_id)
    WHERE vessel_id IS NOT NULL;

ALTER TABLE asset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_tokens FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_asset_tokens ON asset_tokens
    USING (company_id::text = current_setting('app.current_company_id', true));

CREATE TABLE token_ledger_entries (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_token_id UUID NOT NULL REFERENCES asset_tokens(id),
    company_id     UUID NOT NULL,
    entry_type     TEXT NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes          TEXT,
    CONSTRAINT ck_token_ledger_entries_registered
        CHECK (entry_type = 'registered'),
    CONSTRAINT fk_token_ledger_entries_asset_token
        FOREIGN KEY (company_id, asset_token_id)
        REFERENCES asset_tokens (company_id, id)
);

CREATE INDEX idx_token_ledger_entries_company_asset_token
    ON token_ledger_entries(company_id, asset_token_id, recorded_at);

ALTER TABLE token_ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_ledger_entries FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_token_ledger_entries ON token_ledger_entries
    USING (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON asset_tokens TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON asset_tokens TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON token_ledger_entries TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON token_ledger_entries TO harboriq_service;
