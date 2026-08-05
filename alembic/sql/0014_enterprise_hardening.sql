-- HarborIQ v2 — Enterprise Hardening (Phase 16): MFA/TOTP enrollment.
-- Executed verbatim by Alembic migration 0014_enterprise_hardening.
--
-- ============================================================================
-- USERS.MFA_ENABLED_AT — distinguishes "secret set" from "confirmed and active"
-- ============================================================================
-- `mfa_secret_enc` has existed since migration 0001 (nullable BYTEA), but
-- nothing has ever written to it until now. `POST /users/me/mfa/enroll`
-- writes an ENCRYPTED-BUT-UNCONFIRMED secret there immediately (so a user
-- who scans the QR code and then abandons the flow never leaves a half-
-- written row), while `mfa_enabled_at` is set only by `POST
-- /users/me/mfa/confirm` once a real TOTP code has actually been verified
-- against that secret. The login flow (`app/services/auth.py::login`) checks
-- `mfa_enabled_at IS NOT NULL`, never `mfa_secret_enc IS NOT NULL`, so an
-- enrollment that was started but never confirmed can never accidentally
-- lock a user out of their own account.
ALTER TABLE users
    ADD COLUMN mfa_enabled_at TIMESTAMPTZ;

-- ============================================================================
-- MFA BACKUP CODES — recovery when the authenticator device is lost
-- ============================================================================
-- Generated once, at confirm-time, alongside `mfa_enabled_at` being set.
-- Hashed via Argon2id (`app/core/security.py::hash_password`'s same
-- `PasswordHasher`, reused verbatim rather than duplicating hashing logic —
-- see `app/services/mfa.py`), never stored in plaintext, matching the
-- password-hashing convention exactly rather than inventing a second scheme
-- for what is, functionally, a one-time-use short password. `used_at` makes
-- each code single-use: `login/mfa`'s backup-code path claims a code with a
-- conditional `UPDATE ... WHERE used_at IS NULL`, the same "claim, don't
-- just check-then-act" discipline `user_sessions` rotation and the outbox's
-- `FOR UPDATE SKIP LOCKED` claim already use elsewhere in this schema.
CREATE TABLE mfa_backup_codes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id),
    user_id     UUID NOT NULL REFERENCES users(id),
    code_hash   TEXT NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_mfa_backup_codes_user
        FOREIGN KEY (company_id, user_id)
        REFERENCES users (company_id, id) ON DELETE CASCADE
);

-- `users (company_id, id)` is already UNIQUE (migration 0003's
-- `uq_users_company_id`, added for exactly this composite-FK-target reason
-- and reused by job_attachments/purchase_order_line_items ever since), so
-- the FK above needs no new constraint on `users` itself.

CREATE INDEX idx_mfa_backup_codes_user ON mfa_backup_codes (company_id, user_id);
-- A user must never be able to redeem the same still-unused code twice
-- concurrently; the claim UPDATE's `WHERE used_at IS NULL` already prevents
-- double-spend, but a lookup index on the common "find my unused codes"
-- query (enroll/confirm regenerate, and the login/mfa verify path scanning
-- for a match) is worth having explicitly rather than relying on the table
-- scan being small.
CREATE INDEX idx_mfa_backup_codes_user_unused ON mfa_backup_codes (company_id, user_id)
    WHERE used_at IS NULL;

ALTER TABLE mfa_backup_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE mfa_backup_codes FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_mfa_backup_codes ON mfa_backup_codes
    USING (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_backup_codes TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_backup_codes TO harboriq_service;
