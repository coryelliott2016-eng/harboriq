-- HarborIQ v2 — Auth hardening: login rate limiting/lockout, invite tokens.
-- Executed verbatim by Alembic migration 0005.
--
-- Adds:
--   * users.failed_login_attempts / users.locked_until — account lockout
--     state, mutated under the same row lock discipline as the rest of
--     `auth_service.login` (SELECT ... FOR UPDATE inside the one transaction,
--     never a separate round-trip).
--   * token_purpose ENUM value 'user_invite' — the invite-link flow reuses
--     the existing `public_tokens` machinery instead of a parallel table.
--     See README "Email delivery" / "Auth" for the reasoning: `public_tokens`
--     already has hashed-token storage, expiry, max_uses, revocation, and a
--     service-role lookup pattern proven by estimate-approve/invoice-pay.
--     A brand-new `user_invites` table would duplicate all of that for no
--     benefit — the only wrinkle is that `resource_id` (UUID NOT NULL) must
--     be populated for a user who does not exist yet, which the service
--     layer solves the same way `auth_service.signup` already solves it for
--     `company_id`: generate the UUID up front and use it as the id of the
--     row INSERTed at accept-time.
--
-- Per-IP login/reset rate limiting is an in-process counter (see
-- `app/core/rate_limit.py`) — no schema change, so nothing for it here.

-- ============================================================================
-- ACCOUNT LOCKOUT
-- ============================================================================
ALTER TABLE users
    ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN locked_until           TIMESTAMPTZ;

-- ============================================================================
-- INVITE TOKENS — extend the existing public_tokens purpose enum
-- ============================================================================
-- Postgres requires ADD VALUE to run outside a transaction on some versions;
-- IF NOT EXISTS makes this migration idempotent either way and PostgreSQL 12+
-- allows ADD VALUE inside a transaction as long as the new value is not used
-- in that same transaction (which it is not — this migration only alters the
-- type, it never inserts a 'user_invite' row).
ALTER TYPE token_purpose ADD VALUE IF NOT EXISTS 'user_invite';
