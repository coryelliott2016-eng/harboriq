-- HarborIQ uses two database roles for defense in depth:
--   - harboriq_app      : non-owner app role; RLS applies (used by API + tests)
--   - harboriq_service  : BYPASSRLS; cross-tenant platform ops ONLY (webhook
--                         resolution, public-token global lookup, maintenance)
--
-- This script runs as the POSTGRES SUPERUSER during DB initialization (docker
-- entrypoint / CI). It creates extensions + roles that the non-superuser
-- migration role cannot. The migration's `CREATE EXTENSION IF NOT EXISTS` then
-- becomes a no-op.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- On PostgreSQL 15+ the public schema no longer grants CREATE to PUBLIC by
-- default, so the non-superuser migration role cannot create tables. Grant
-- schema privileges here (superuser context) BEFORE the migration runs.
GRANT USAGE, CREATE ON SCHEMA public TO harboriq_service;
GRANT USAGE ON SCHEMA public TO harboriq_app;

-- Role creation is idempotent so it is safe to re-run on an existing cluster.
DO $$ BEGIN
  CREATE ROLE harboriq_app WITH LOGIN PASSWORD 'harboriq_app_pass';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE ROLE harboriq_service WITH LOGIN PASSWORD 'harboriq_service_pass' BYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
