-- HarborIQ v2 — Core CRM / operations domain (customers, vessels, jobs).
-- Executed verbatim by Alembic migration 0003_crm_operations.
--
-- 0001 created skeleton `customers`, `vessels` and `jobs` tables with just
-- enough columns to hang RLS and the money/state-machine fixes off. This
-- migration fills them out into the real operational domain and adds the job
-- line items that the invoicing phase will bill from.
--
-- Two structural corrections beyond the new columns:
--
--   1. TENANT-SAFE FOREIGN KEYS. A plain `REFERENCES customers(id)` is checked
--      by an internal system query that is NOT subject to RLS, so tenant A
--      could point its vessel at tenant B's customer id and the FK would
--      happily accept it. Every intra-tenant reference is therefore a COMPOSITE
--      key on (company_id, <id>), which makes a cross-tenant reference
--      unrepresentable rather than merely unlikely.
--
--   2. `updated_at`. Services write it explicitly (this repo uses raw SQL, not
--      ORM flush hooks), so no trigger is involved.

-- ============================================================================
-- ENUMS
-- ============================================================================
CREATE TYPE job_priority       AS ENUM ('low', 'normal', 'high', 'urgent');
CREATE TYPE job_line_item_kind AS ENUM ('labor', 'part', 'fee');

-- ============================================================================
-- COMPOSITE-KEY TARGETS
-- ============================================================================
-- (company_id, id) must be UNIQUE to be referenced by a composite FK. `id` is
-- already the primary key, so these add no new row-uniqueness rule — they only
-- publish the pair as a legal FK target.
ALTER TABLE users     ADD CONSTRAINT uq_users_company_id     UNIQUE (company_id, id);
ALTER TABLE customers ADD CONSTRAINT uq_customers_company_id UNIQUE (company_id, id);
ALTER TABLE vessels   ADD CONSTRAINT uq_vessels_company_id   UNIQUE (company_id, id);
ALTER TABLE jobs      ADD CONSTRAINT uq_jobs_company_id      UNIQUE (company_id, id);
-- Reserved for the invoicing phase, which will point job_line_items at invoices.
ALTER TABLE invoices  ADD CONSTRAINT uq_invoices_company_id  UNIQUE (company_id, id);

-- ============================================================================
-- CUSTOMERS
-- ============================================================================
ALTER TABLE customers
    ADD COLUMN company_name TEXT,
    ADD COLUMN country      TEXT,
    ADD COLUMN notes        TEXT,
    ADD COLUMN updated_at   TIMESTAMPTZ NOT NULL DEFAULT now();

-- A customer is a person, a business, or both; requiring `first_name` would be
-- wrong for "Bayside Charters LLC" and requiring `company_name` wrong for a
-- private owner. At least one identifying name must be present.
ALTER TABLE customers
    ADD CONSTRAINT ck_customers_has_a_name CHECK (
        COALESCE(NULLIF(BTRIM(first_name),   ''),
                 NULLIF(BTRIM(last_name),    ''),
                 NULLIF(BTRIM(company_name), '')) IS NOT NULL
    );

-- Name lookup and the customer list's default ordering.
CREATE INDEX idx_customers_company_name
    ON customers (company_id, last_name, first_name);
-- Partial: most customers have an email, but it is not required and NULLs are
-- not worth indexing. Not UNIQUE — shops legitimately share a family address.
CREATE INDEX idx_customers_company_email
    ON customers (company_id, email) WHERE email IS NOT NULL;

-- ============================================================================
-- VESSELS
-- ============================================================================
ALTER TABLE vessels
    ADD COLUMN engine_make      TEXT,
    ADD COLUMN engine_model     TEXT,
    ADD COLUMN engine_count     INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN beam_ft          NUMERIC(6,2),
    ADD COLUMN draft_ft         NUMERIC(6,2),
    ADD COLUMN storage_location TEXT,
    ADD COLUMN slip_number      TEXT,
    ADD COLUMN notes            TEXT,
    ADD COLUMN updated_at       TIMESTAMPTZ NOT NULL DEFAULT now();

-- A vessel belongs to a customer. 0001 left this nullable; the domain requires
-- an owner. Deliberately NOT backfilled or cleaned up: if an ownerless vessel
-- somehow exists, this SET NOT NULL fails the migration and an operator decides
-- what the row should say. A migration must not quietly delete service history.
ALTER TABLE vessels ALTER COLUMN customer_id SET NOT NULL;

-- Replace 0001's tenant-blind FK with the composite one.
ALTER TABLE vessels DROP CONSTRAINT vessels_customer_id_fkey;
ALTER TABLE vessels
    ADD CONSTRAINT fk_vessels_customer
        FOREIGN KEY (company_id, customer_id)
        REFERENCES customers (company_id, id);

ALTER TABLE vessels
    ADD CONSTRAINT ck_vessels_year        CHECK (year IS NULL OR year BETWEEN 1850 AND 2200),
    ADD CONSTRAINT ck_vessels_length      CHECK (length_ft IS NULL OR length_ft > 0),
    ADD CONSTRAINT ck_vessels_beam        CHECK (beam_ft IS NULL OR beam_ft > 0),
    ADD CONSTRAINT ck_vessels_draft       CHECK (draft_ft IS NULL OR draft_ft > 0),
    ADD CONSTRAINT ck_vessels_engine_hours CHECK (engine_hours IS NULL OR engine_hours >= 0),
    ADD CONSTRAINT ck_vessels_engine_count CHECK (engine_count >= 0);

CREATE INDEX idx_vessels_company_customer ON vessels (company_id, customer_id);
-- A Hull Identification Number is globally unique to a hull, so within one
-- shop it must not be entered twice. Partial: HIN is often unknown on intake.
CREATE UNIQUE INDEX uq_vessels_company_hull_id
    ON vessels (company_id, hull_id) WHERE hull_id IS NOT NULL;

-- ============================================================================
-- JOBS / WORK ORDERS
-- ============================================================================
ALTER TABLE jobs
    ADD COLUMN title             TEXT,
    ADD COLUMN description      TEXT,
    ADD COLUMN priority         job_priority NOT NULL DEFAULT 'normal',
    ADD COLUMN scheduled_end_at TIMESTAMPTZ,
    ADD COLUMN started_at       TIMESTAMPTZ,
    ADD COLUMN completed_at     TIMESTAMPTZ,
    ADD COLUMN canceled_at      TIMESTAMPTZ,
    ADD COLUMN hold_reason      TEXT,
    ADD COLUMN notes            TEXT,
    ADD COLUMN updated_at       TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill before tightening: a work order with no title is not actionable.
UPDATE jobs SET title = 'Untitled work order' WHERE title IS NULL;
ALTER TABLE jobs ALTER COLUMN title SET NOT NULL;

-- A job is always for a customer; the vessel and technician stay optional
-- (yard/shop work with no boat attached, and unassigned intake). As with
-- vessels above, an unattributable row fails the migration rather than
-- being deleted.
ALTER TABLE jobs ALTER COLUMN customer_id SET NOT NULL;

ALTER TABLE jobs DROP CONSTRAINT jobs_customer_id_fkey;
ALTER TABLE jobs DROP CONSTRAINT jobs_vessel_id_fkey;
ALTER TABLE jobs DROP CONSTRAINT jobs_technician_id_fkey;
ALTER TABLE jobs
    ADD CONSTRAINT fk_jobs_customer
        FOREIGN KEY (company_id, customer_id)
        REFERENCES customers (company_id, id),
    ADD CONSTRAINT fk_jobs_vessel
        FOREIGN KEY (company_id, vessel_id)
        REFERENCES vessels (company_id, id),
    ADD CONSTRAINT fk_jobs_technician
        FOREIGN KEY (company_id, technician_id)
        REFERENCES users (company_id, id);

ALTER TABLE jobs
    ADD CONSTRAINT ck_jobs_title_not_blank CHECK (BTRIM(title) <> ''),
    ADD CONSTRAINT ck_jobs_schedule_window CHECK (
        scheduled_end_at IS NULL
        OR scheduled_at IS NULL
        OR scheduled_end_at >= scheduled_at
    );

-- 0001 already created idx_jobs_company_scheduled(company_id, scheduled_at),
-- which serves the date-range calendar query. These serve the two board views:
-- "my work" and "the open queue".
CREATE INDEX idx_jobs_company_technician_scheduled
    ON jobs (company_id, technician_id, scheduled_at);
CREATE INDEX idx_jobs_company_status_scheduled
    ON jobs (company_id, status, scheduled_at);
CREATE INDEX idx_jobs_company_customer ON jobs (company_id, customer_id);
CREATE INDEX idx_jobs_company_vessel
    ON jobs (company_id, vessel_id) WHERE vessel_id IS NOT NULL;

-- ============================================================================
-- JOB LINE ITEMS — labor / parts / fees
-- ============================================================================
-- Forward-compatible with the invoicing phase, which will set invoice_id and
-- invoiced_at rather than needing a schema change:
--   * money is NUMERIC(12,2) with a STORED generated line_total, matching
--     estimate_line_items;
--   * `quantity` is NUMERIC(12,2) rather than estimate_line_items' INTEGER,
--     because labor is billed in fractional hours (1.50 h) while a parts count
--     is just a whole number in the same column;
--   * `taxable` is carried per line so tax_total can be computed at invoice
--     time without re-deriving it from the item kind.
CREATE TABLE job_line_items (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        UUID NOT NULL REFERENCES companies(id),
    job_id            UUID NOT NULL,
    kind              job_line_item_kind NOT NULL,
    description       TEXT NOT NULL,
    -- Set when the line came from stock, so invoicing can report cost of goods
    -- and a reversal knows what to put back.
    inventory_item_id UUID REFERENCES inventory_items(id),
    quantity          NUMERIC(12,2) NOT NULL
                          CONSTRAINT ck_job_line_items_quantity CHECK (quantity > 0),
    unit_price        NUMERIC(12,2) NOT NULL DEFAULT 0
                          CONSTRAINT ck_job_line_items_unit_price CHECK (unit_price >= 0),
    line_total        NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    taxable           BOOLEAN NOT NULL DEFAULT true,
    -- True once the stock deduction has actually happened via
    -- POST /api/v1/inventory/use, so a part is never deducted twice.
    inventory_committed BOOLEAN NOT NULL DEFAULT false,
    -- Reserved for the invoicing phase; nothing writes these yet.
    invoice_id        UUID,
    invoiced_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_job_line_items_job
        FOREIGN KEY (company_id, job_id)
        REFERENCES jobs (company_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_job_line_items_invoice
        FOREIGN KEY (company_id, invoice_id)
        REFERENCES invoices (company_id, id),
    CONSTRAINT ck_job_line_items_description CHECK (BTRIM(description) <> ''),
    -- Only a part can be drawn from stock, and only a stock line can be
    -- marked committed.
    CONSTRAINT ck_job_line_items_stock_is_a_part CHECK (
        inventory_item_id IS NULL OR kind = 'part'
    ),
    CONSTRAINT ck_job_line_items_committed_has_stock CHECK (
        inventory_committed = false OR inventory_item_id IS NOT NULL
    ),
    CONSTRAINT ck_job_line_items_invoiced_together CHECK (
        (invoice_id IS NULL) = (invoiced_at IS NULL)
    )
);

CREATE INDEX idx_job_line_items_job ON job_line_items (company_id, job_id);
-- The invoicing phase's "what is billable on this job" query.
CREATE INDEX idx_job_line_items_uninvoiced
    ON job_line_items (company_id, job_id) WHERE invoice_id IS NULL;

-- ============================================================================
-- ROW-LEVEL SECURITY — same backstop as every other tenant table
-- ============================================================================
-- customers, vessels and jobs already had ENABLE + FORCE + a policy from 0001;
-- only the new table needs arming.
ALTER TABLE job_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_line_items FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_job_line_items ON job_line_items
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- GRANTS (0001's GRANT ... ON ALL TABLES only covered tables existing then)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON job_line_items TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON job_line_items TO harboriq_service;
