-- HarborIQ v2 — Real authentication + tenant onboarding.
-- Executed verbatim by Alembic migration 0002_auth.
--
-- Adds:
--   * user_role enum (replaces the free-text users.role column)
--   * platform-wide unique email (one login identity == one company, see README)
--   * user_sessions        — hashed, rotating refresh tokens (opaque, not JWT)
--   * password_reset_tokens — hashed, single-use reset tokens
--
-- Both new tables follow the public_tokens security model already in 0001:
-- store only SHA-256(token), never the raw value; explicit expiry + revocation;
-- tenant-isolated by RLS with the service role used ONLY for the global
-- token/email lookup that precedes entering tenant_context.

-- ============================================================================
-- USER ROLES — explicit enum instead of an implicit status string
-- ============================================================================
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'office', 'technician');

ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users
    ALTER COLUMN role TYPE user_role USING role::user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'technician';

-- Login resolves a user by email with no tenant context yet, so email must
-- identify exactly one account platform-wide. NOTE: a unique index is enforced
-- across ALL rows regardless of RLS, so this also prevents a tenant from
-- silently shadowing another tenant's login identity.
CREATE UNIQUE INDEX uq_users_email_global ON users (email);

-- ============================================================================
-- REFRESH-TOKEN SESSIONS
-- ============================================================================
-- One row per issued refresh token. Rotation inserts a NEW row sharing the
-- family_id and marks the old row rotated_at; presenting an already-rotated
-- token is treated as theft and revokes the whole family.
CREATE TABLE user_sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id         UUID NOT NULL REFERENCES companies(id),
    user_id            UUID NOT NULL REFERENCES users(id),
    family_id          UUID NOT NULL,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    expires_at         TIMESTAMPTZ NOT NULL,
    rotated_at         TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    revoked_reason     TEXT,
    user_agent         TEXT,
    ip                 INET,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_sessions_family ON user_sessions(family_id);
CREATE INDEX idx_user_sessions_user ON user_sessions(company_id, user_id);
-- Sweeping expired sessions is a maintenance job (service role).
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at)
    WHERE revoked_at IS NULL;

-- ============================================================================
-- PASSWORD RESET TOKENS
-- ============================================================================
CREATE TABLE password_reset_tokens (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id),
    user_id      UUID NOT NULL REFERENCES users(id),
    token_hash   TEXT NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ NOT NULL,
    used_at      TIMESTAMPTZ,
    requested_ip INET,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_password_reset_user ON password_reset_tokens(company_id, user_id);

-- ============================================================================
-- ROW-LEVEL SECURITY (same backstop as every other tenant table)
-- ============================================================================
ALTER TABLE user_sessions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens  ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions          FORCE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens  FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_user_sessions ON user_sessions
    USING (company_id::text = current_setting('app.current_company_id', true));
CREATE POLICY tenant_isolation_password_resets ON password_reset_tokens
    USING (company_id::text = current_setting('app.current_company_id', true));

-- 0001 left `companies` itself without RLS, so any app-role session could read
-- every tenant's row. Now that authenticated requests carry a verified tenant,
-- close it: a tenant may only see its own company. Signup pre-generates the
-- company UUID and sets the GUC before INSERT so the WITH CHECK passes.
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_companies ON companies
    USING (id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- GRANTS (0001's GRANT ... ON ALL TABLES only covered tables existing then)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON user_sessions         TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON password_reset_tokens TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_sessions         TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON password_reset_tokens TO harboriq_service;
