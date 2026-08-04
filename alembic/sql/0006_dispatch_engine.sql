-- HarborIQ v2 — AI Dispatch Engine (rule-based scoring) schema additions.
-- Executed verbatim by Alembic migration 0006_dispatch_engine.
--
-- Phase 7 adds a transparent, explainable, rule-based job-priority scorer
-- (see app/services/dispatch.py) considering urgency, revenue, customer
-- value, technician travel distance and skill fit. Machine learning is
-- explicitly deferred until the platform has accumulated enough real
-- repair-outcome data (~500+ completed jobs with recorded outcomes) to train
-- something meaningful — see README "AI dispatch engine" for the reasoning.
-- This migration only adds the columns that support of that rule-based
-- scorer; it does not add any ML infrastructure.
--
-- Four kinds of new columns:
--   1. `users.skills` — free-text technician skill tags, matched against a
--      job's `required_skills` for the technician-fit factor. No normalized
--      skills-taxonomy table yet (see comment on the column below).
--   2. `users.home_latitude/home_longitude`, `companies.latitude/longitude`,
--      `customers.latitude/longitude` — coordinates for the haversine
--      distance factor. All nullable: geocoding customer addresses against a
--      real API is out of scope for this phase, so these will be NULL for
--      most rows for a while. The scorer (app/services/dispatch.py) degrades
--      the distance factor to neutral rather than erroring when either side
--      is missing coordinates.
--   3. `jobs.required_skills` — free-text skill tags a job needs, matched
--      against a candidate technician's `users.skills`.
--   4. `jobs.dispatch_score` / `dispatch_score_breakdown` / `dispatch_scored_at`
--      — the engine's last computed, technician-independent score for this
--      job (urgency + revenue + customer value), cached on the row so the
--      intake queue / schedule board does not recompute it on every page
--      load. Recomputed on demand via `POST /jobs/{id}/dispatch/recompute`.

-- ============================================================================
-- USERS — technician skills + home base coordinates
-- ============================================================================
ALTER TABLE users
    ADD COLUMN skills TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN home_latitude  NUMERIC(9,6),
    ADD COLUMN home_longitude NUMERIC(9,6);

-- A normalized skills table (one row per skill, with a per-technician
-- proficiency level) is the natural upgrade once there is a real need to
-- query "who's the best outboard tech", or to enforce a canonical skill
-- vocabulary instead of free text. Not built now: with a handful of
-- technicians per tenant and no proficiency-ranking UI yet, a TEXT[] column
-- is simpler, needs no extra joins, and captures exactly what the scorer
-- currently uses (set overlap, not a ranked score per skill).

ALTER TABLE users
    ADD CONSTRAINT ck_users_home_latlng_pair
        CHECK ((home_latitude IS NULL) = (home_longitude IS NULL));

-- ============================================================================
-- COMPANIES — shop home-base coordinates (distance-scoring fallback)
-- ============================================================================
ALTER TABLE companies
    ADD COLUMN latitude  NUMERIC(9,6),
    ADD COLUMN longitude NUMERIC(9,6);

ALTER TABLE companies
    ADD CONSTRAINT ck_companies_latlng_pair
        CHECK ((latitude IS NULL) = (longitude IS NULL));

-- ============================================================================
-- CUSTOMERS — coordinates for the distance factor
-- ============================================================================
-- Geocoding address_line1/city/state/postal_code against a real geocoding API
-- is explicitly OUT of scope for this phase (see README). These columns exist
-- so a future phase can populate them and so the scorer has a real field to
-- read once populated; for now they will mostly be NULL, and the scorer must
-- (and does) degrade gracefully rather than fabricate a distance.
ALTER TABLE customers
    ADD COLUMN latitude  NUMERIC(9,6),
    ADD COLUMN longitude NUMERIC(9,6);

ALTER TABLE customers
    ADD CONSTRAINT ck_customers_latlng_pair
        CHECK ((latitude IS NULL) = (longitude IS NULL));

-- ============================================================================
-- JOBS — required skills + cached dispatch score
-- ============================================================================
ALTER TABLE jobs
    ADD COLUMN required_skills TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN dispatch_score NUMERIC(6,2),
    ADD COLUMN dispatch_score_breakdown JSONB,
    ADD COLUMN dispatch_scored_at TIMESTAMPTZ;
