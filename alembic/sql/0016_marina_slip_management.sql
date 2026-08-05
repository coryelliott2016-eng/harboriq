-- HarborIQ v2 — Marina/Slip Management (Phase 15), part 2 of 2.
-- Executed verbatim by Alembic migration 0016_marina_slip_management.
-- (Part 1, migration 0015, only added job_line_item_kind's new `storage`
-- value in its own transaction -- see that file's header for why.)
--
-- Business-model fork, explicitly approved: this phase serves fixed-location
-- marinas/boatyards (physical slips, dry-stack storage) alongside the
-- mobile-mechanic wedge every prior phase targeted. A marina customer is
-- still a `Customer` (Phase 2); a boat in a slip is still a `Vessel`
-- (Phase 2) -- nothing here duplicates either table.
--
-- ============================================================================
-- btree_gist — required for the exclusion constraint below
-- ============================================================================
-- Postgres has no native way to say "no two rows with the same slip_id may
-- have overlapping date ranges" as a CHECK (CHECK constraints cannot see
-- other rows). An EXCLUDE constraint can, but EXCLUDE needs an operator
-- class for every column it compares, and there is no default GiST opclass
-- for a plain equality comparison on a UUID column -- btree_gist supplies
-- one (an equality-comparable btree type wrapped for use inside a GiST
-- index), which is the standard, documented way to combine "equal on this
-- column" with "overlaps on this range" in one exclusion constraint.
-- Installing an extension requires superuser, so in production/CI this is a
-- no-op here (already installed by docker-entrypoint-initdb.d/00_roles.sql,
-- run as the postgres superuser before this migration -- same pattern as
-- pgcrypto/citext); kept here too so a local `alembic upgrade head` run
-- against a cluster that already has superuser-level CREATE EXTENSION
-- rights on the migration role still works standalone.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ============================================================================
-- SLIPS — wet slips, dry-stack spaces, and moorings share one table
-- ============================================================================
-- Design choice (documented per the phase spec's "use your judgement"):
-- ONE `slips` table with a `slip_type` discriminator, not a separate
-- `dry_stack_spaces` table. A wet slip and a dry-stack rack space need the
-- same core fields -- identifier, dimensions, status, a rental rate -- and
-- diverge only on a handful of columns (dry stack needs `rack_level`/
-- `rack_position` for forklift retrieval; a wet slip's `depth_ft` is
-- meaningless for a rack space stacked in a shed). Two nearly-identical
-- tables would mean every query that wants "all rentable spaces" (the slip
-- map, availability search, billing generation) has to UNION them; one
-- table with a handful of type-specific nullable columns keeps that query
-- single and simple, at the minor cost of `depth_ft`/`rack_level` being
-- mutually meaningless depending on `slip_type` (enforced by CHECK below,
-- not just left to convention).
CREATE TYPE slip_type AS ENUM ('wet_slip', 'dry_stack', 'mooring');
CREATE TYPE slip_status AS ENUM ('available', 'occupied', 'reserved', 'maintenance');

CREATE TABLE slips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    -- e.g. "A-12", "DS-3-2" -- the marina's own numbering, not assumed to be
    -- purely numeric or globally unique across marinas (hence per-tenant,
    -- not globally, unique below).
    identifier      TEXT NOT NULL,
    slip_type       slip_type NOT NULL DEFAULT 'wet_slip',
    status          slip_status NOT NULL DEFAULT 'available',
    length_ft       NUMERIC(6, 2) CHECK (length_ft IS NULL OR length_ft > 0),
    width_ft        NUMERIC(6, 2) CHECK (width_ft IS NULL OR width_ft > 0),
    -- Water depth at low tide for a wet slip/mooring; meaningless for a
    -- dry-stack rack space (CHECK below enforces that pairing).
    depth_ft        NUMERIC(6, 2) CHECK (depth_ft IS NULL OR depth_ft > 0),
    -- Dry-stack-only: which rack level/bay a forklift needs to reach this
    -- space. NULL for wet slips/moorings, enforced below.
    rack_level      INTEGER CHECK (rack_level IS NULL OR rack_level >= 0),
    rack_position   TEXT,
    -- Optional GPS coordinates for a customer-facing "find my dock" view on
    -- a real waterfront property -- NOT required for the staff slip map
    -- (see README for why the staff map is a CSS grid keyed on `identifier`,
    -- not these coordinates). NULL is the common case; a marina with no
    -- interest in that customer-facing view never needs to set these.
    latitude        NUMERIC(9, 6),
    longitude       NUMERIC(9, 6),
    monthly_rate    NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (monthly_rate >= 0),
    daily_rate      NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (daily_rate >= 0),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_slips_depth_only_wet_or_mooring CHECK (
        depth_ft IS NULL OR slip_type IN ('wet_slip', 'mooring')
    ),
    CONSTRAINT ck_slips_rack_only_dry_stack CHECK (
        (rack_level IS NULL AND rack_position IS NULL) OR slip_type = 'dry_stack'
    ),
    CONSTRAINT ck_slips_latlng_pair CHECK ((latitude IS NULL) = (longitude IS NULL))
);

-- Per-tenant unique identifier -- "A-12" only has to be unambiguous within
-- one marina's numbering, same "scoped, not global" uniqueness rule as
-- customers/vessels/inventory elsewhere in this schema.
CREATE UNIQUE INDEX uq_slips_company_identifier ON slips (company_id, identifier);
CREATE INDEX idx_slips_company_status ON slips (company_id, status);
-- Target of slip_reservations' and dry_stack_launch_requests' composite FKs,
-- matching the uq_jobs_company_id / uq_purchase_orders_company_id convention.
ALTER TABLE slips ADD CONSTRAINT uq_slips_company_id UNIQUE (company_id, id);

ALTER TABLE slips ENABLE ROW LEVEL SECURITY;
ALTER TABLE slips FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_slips ON slips
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- SLIP RESERVATIONS — the state machine + the double-booking guard
-- ============================================================================
-- Status transitions are enforced in app/services/state_machines.py
-- (SlipReservationSM), mirroring JobSM/PurchaseOrderSM:
--   pending -> {confirmed, cancelled}
--   confirmed -> {checked_in, cancelled}
--   checked_in -> {checked_out}
--   checked_out / cancelled are terminal.
CREATE TYPE slip_reservation_status AS ENUM (
    'pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled'
);

CREATE TABLE slip_reservations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    slip_id         UUID NOT NULL,
    customer_id     UUID NOT NULL,
    -- Optional: a reservation can be taken before the specific boat is known
    -- (e.g. phone booking "a 30-footer for the week of the 4th") and filled
    -- in at check-in, same nullable-until-known posture as
    -- job_line_items.inventory_item_id elsewhere in this schema.
    vessel_id       UUID,
    status          slip_reservation_status NOT NULL DEFAULT 'pending',
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    -- Generated, not application-computed, so the exclusion constraint below
    -- always compares against a value that is guaranteed consistent with
    -- start_date/end_date -- there is no code path that could write a
    -- daterange that disagrees with the two columns it is derived from.
    -- '[]' -- inclusive of both endpoints -- matches how a marina actually
    -- books nights: a reservation for Aug 5 through Aug 7 occupies the slip
    -- ON Aug 7, not up to (but excluding) it.
    stay_range      DATERANGE GENERATED ALWAYS AS (daterange(start_date, end_date, '[]')) STORED,
    checked_in_at   TIMESTAMPTZ,
    checked_out_at  TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_slip_reservations_dates CHECK (end_date >= start_date),
    CONSTRAINT fk_slip_reservations_slip
        FOREIGN KEY (company_id, slip_id) REFERENCES slips (company_id, id),
    CONSTRAINT fk_slip_reservations_customer
        FOREIGN KEY (company_id, customer_id) REFERENCES customers (company_id, id),
    CONSTRAINT fk_slip_reservations_vessel
        FOREIGN KEY (company_id, vessel_id) REFERENCES vessels (company_id, id),

    -- THE database-level double-booking guard. Same philosophy this
    -- codebase already applies to RLS/inventory concurrency: the invariant
    -- ("this slip is never booked to two overlapping stays") is enforced by
    -- Postgres itself, not just by application code that could race or have
    -- a bug. `cancelled` reservations are excluded from the comparison (a
    -- cancelled booking must not permanently block the slip it once held);
    -- `checked_out` bookings ARE still compared -- a checked-out stay is a
    -- historical fact about dates that really were occupied, and while in
    -- practice a checked-out stay's end_date is in the past and therefore
    -- rarely overlaps a NEW booking's range, there is no reason to weaken
    -- the guard for it.
    CONSTRAINT ex_slip_reservations_no_overlap
        EXCLUDE USING gist (slip_id WITH =, stay_range WITH &&)
        WHERE (status <> 'cancelled')
);

ALTER TABLE slip_reservations ADD CONSTRAINT uq_slip_reservations_company_id UNIQUE (company_id, id);

CREATE INDEX idx_slip_reservations_company_slip ON slip_reservations (company_id, slip_id);
CREATE INDEX idx_slip_reservations_company_customer ON slip_reservations (company_id, customer_id);
CREATE INDEX idx_slip_reservations_company_status ON slip_reservations (company_id, status);

ALTER TABLE slip_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE slip_reservations FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_slip_reservations ON slip_reservations
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- DRY-STACK LAUNCH REQUESTS — lightweight retrieval/launch scheduling
-- ============================================================================
-- Explicitly NOT a crane/forklift dispatch system (per the phase spec): one
-- row per "the owner of this reservation's boat wants it in the water by
-- such-and-such a time," staff mark it scheduled/completed. No equipment
-- inventory, no operator assignment, no IoT integration -- see the README's
-- "What's intentionally NOT here yet" for the full deferred list.
CREATE TYPE dry_stack_launch_status AS ENUM (
    'requested', 'scheduled', 'completed', 'cancelled'
);

CREATE TABLE dry_stack_launch_requests (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            UUID NOT NULL REFERENCES companies(id),
    slip_reservation_id   UUID NOT NULL,
    requested_for         TIMESTAMPTZ NOT NULL,
    status                dry_stack_launch_status NOT NULL DEFAULT 'requested',
    scheduled_for         TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_dry_stack_launch_reservation
        FOREIGN KEY (company_id, slip_reservation_id)
        REFERENCES slip_reservations (company_id, id) ON DELETE CASCADE
);

CREATE INDEX idx_dry_stack_launch_company_reservation
    ON dry_stack_launch_requests (company_id, slip_reservation_id);
CREATE INDEX idx_dry_stack_launch_company_status
    ON dry_stack_launch_requests (company_id, status);

ALTER TABLE dry_stack_launch_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE dry_stack_launch_requests FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_dry_stack_launch_requests ON dry_stack_launch_requests
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- STORAGE BILLING — extend job_line_items rather than invent a parallel
-- invoice-line-item table
-- ============================================================================
-- Phase 3 already gave invoices a line-item table -- job_line_items, despite
-- the name -- with a nullable invoice_id/invoiced_at pair and a `kind` enum
-- (labor/part/fee, now also `storage` as of migration 0015). A slip
-- reservation's rental charge is the same shape of fact ("N units at a unit
-- price, taxable or not, eventually frozen onto an invoice") as a labor or
-- parts line; the only thing missing is a way to point a line item at a
-- reservation instead of a job. Rather than inventing `invoice_line_items`
-- as a second, parallel table (violating the phase spec's explicit "reuse
-- the existing machinery" instruction and this codebase's established
-- one-writer-per-concern discipline), this migration:
--   1. makes job_line_items.job_id NULLABLE (a real, deliberate schema
--      change -- it was NOT NULL since migration 0003, when every line item
--      necessarily came from a job) and adds a nullable, tenant-safe
--      composite FK to slip_reservations,
--   2. adds a CHECK requiring EXACTLY ONE of job_id / slip_reservation_id to
--      be set, so a line item is always traceable to exactly one billable
--      source and "belongs to nothing" / "belongs to both" are both
--      unrepresentable.
ALTER TABLE job_line_items ALTER COLUMN job_id DROP NOT NULL;

ALTER TABLE job_line_items ADD COLUMN slip_reservation_id UUID;

ALTER TABLE job_line_items
    ADD CONSTRAINT fk_job_line_items_slip_reservation
        FOREIGN KEY (company_id, slip_reservation_id)
        REFERENCES slip_reservations (company_id, id);

ALTER TABLE job_line_items
    ADD CONSTRAINT ck_job_line_items_exactly_one_source CHECK (
        (job_id IS NOT NULL AND slip_reservation_id IS NULL)
        OR (job_id IS NULL AND slip_reservation_id IS NOT NULL)
    );

-- Only a storage line may point at a reservation (mirrors
-- ck_job_line_items_stock_is_a_part's "only this kind may carry this FK").
ALTER TABLE job_line_items
    ADD CONSTRAINT ck_job_line_items_storage_has_reservation CHECK (
        slip_reservation_id IS NULL OR kind = 'storage'
    );

CREATE INDEX idx_job_line_items_slip_reservation
    ON job_line_items (company_id, slip_reservation_id)
    WHERE slip_reservation_id IS NOT NULL;

-- ============================================================================
-- GRANTS (0001's GRANT ... ON ALL TABLES only covered tables existing then)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON slips TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON slips TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON slip_reservations TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON slip_reservations TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON dry_stack_launch_requests TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON dry_stack_launch_requests TO harboriq_service;
