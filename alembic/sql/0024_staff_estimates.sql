-- 0024 — Staff-authored estimates.
--
-- Until this migration the `estimates` table could be viewed and approved by
-- a customer (portal + public approval token) but no staff API could create
-- one, so the estimate -> approval -> invoice workflow was not reachable
-- end-to-end. The original `estimate_line_items` shape also could not carry
-- what a marine estimate needs:
--
--   * fractional labor hours (quantity was INTEGER),
--   * the labor / part / fee distinction (a diagnostic fee is a `fee` line),
--   * per-line taxability (labor is commonly non-taxable).
--
-- This migration aligns `estimate_line_items` with `job_line_items` so an
-- approved estimate converts into an invoice without lossy re-mapping, and
-- adds `tax_rate`, `sent_at` and `updated_at` to `estimates`. Existing rows
-- keep their values (INTEGER -> NUMERIC is lossless; new columns default).

ALTER TABLE estimate_line_items DROP COLUMN line_total;

ALTER TABLE estimate_line_items
    ALTER COLUMN quantity TYPE NUMERIC(12,2) USING quantity::numeric;

ALTER TABLE estimate_line_items
    ADD COLUMN line_total NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    ADD COLUMN kind job_line_item_kind NOT NULL DEFAULT 'part',
    ADD COLUMN taxable BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN position INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- `storage` lines exist only for slip-reservation billing; they never belong
-- on a service estimate.
ALTER TABLE estimate_line_items
    ADD CONSTRAINT ck_estimate_line_items_kind_not_storage CHECK (kind <> 'storage');

ALTER TABLE estimates
    ADD COLUMN tax_rate NUMERIC(5,4) NOT NULL DEFAULT 0
        CONSTRAINT ck_estimates_tax_rate_range CHECK (tax_rate >= 0 AND tax_rate <= 1),
    ADD COLUMN sent_at TIMESTAMPTZ,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN notes TEXT;

CREATE INDEX IF NOT EXISTS ix_estimate_line_items_estimate_id
    ON estimate_line_items (estimate_id);
CREATE INDEX IF NOT EXISTS ix_estimates_company_job
    ON estimates (company_id, job_id);
