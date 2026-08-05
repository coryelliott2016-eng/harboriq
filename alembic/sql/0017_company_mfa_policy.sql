-- Phase 17, Area C.2: per-company admin-forced MFA policy.
--
-- `mfa_required` lets an owner/admin require every user in the company to
-- have MFA enrolled (`users.mfa_enabled_at IS NOT NULL`, added in
-- migration 0014) before they can complete login. Defaults to false so
-- existing tenants are unaffected until an admin opts in.
ALTER TABLE companies
    ADD COLUMN mfa_required BOOLEAN NOT NULL DEFAULT false;
