-- HarborIQ v2 — Live Dispatch Board + Map + Two-Way SMS (Phase 11).
-- Executed verbatim by Alembic migration 0010_dispatch_board.
--
-- ============================================================================
-- USERS — live (best-effort) technician location, distinct from home base
-- ============================================================================
-- `users.home_latitude`/`home_longitude` (migration 0006) represent a static
-- home port/shop base used by the dispatch engine's distance factor when no
-- better signal exists. This is a DIFFERENT concept: where a technician
-- actually is right now, reported by their own device via
-- `POST /users/me/location-ping` while they have the staff web app open in a
-- phone browser. There is no mobile app yet (Phase 12) and no background
-- tracking -- `location_updated_at` lets every consumer (the dispatch board
-- map, a future staleness warning) tell "fresh" from "reported 6 hours ago,
-- probably stale" rather than treating a ping from this morning as if it
-- were live right now.
ALTER TABLE users ADD COLUMN current_latitude  NUMERIC(9, 6);
ALTER TABLE users ADD COLUMN current_longitude NUMERIC(9, 6);
ALTER TABLE users ADD COLUMN location_updated_at TIMESTAMPTZ;

ALTER TABLE users
    ADD CONSTRAINT ck_users_current_latlng_pair
        CHECK ((current_latitude IS NULL) = (current_longitude IS NULL));

-- ============================================================================
-- MESSAGES — channel column (Phase 9 table gets its first new column)
-- ============================================================================
-- Every message so far has arrived through the customer portal. This phase
-- adds a second channel -- inbound/outbound SMS -- so a customer's reply
-- texted to the shop's Twilio number lands in the exact same thread/table as
-- a portal message rather than a parallel inbox. `channel` records how the
-- message ARRIVED (portal vs sms); a staff reply's outbound channel is
-- decided at reply time by `app/services/messages.py` (SMS if the customer's
-- most recent inbound message came in via SMS and they have a phone number,
-- portal/email otherwise), not stored redundantly here.
-- Backfilled 'portal' for every historical row so the column is never NULL
-- for data that predates this phase, matching the NOT NULL DEFAULT pattern
-- already used for e.g. jobs.required_skills.
ALTER TABLE messages ADD COLUMN channel TEXT NOT NULL DEFAULT 'portal';

ALTER TABLE messages
    ADD CONSTRAINT ck_messages_channel
        CHECK (channel IN ('portal', 'sms'));
