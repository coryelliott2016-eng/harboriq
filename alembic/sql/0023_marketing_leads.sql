-- ============================================================================
-- 0023 — Marketing leads (public signup capture from harboriq.com / GTM site)
-- ============================================================================
-- Platform-level table: NOT tenant-scoped. Leads arrive before any company
-- exists (trial / demo request). No company_id, no RLS.
--
-- Access model matches stripe_processed_events / crypto_processed_events
-- after migration 0022: SERVICE ROLE ONLY (harboriq_service). The public
-- POST /api/v1/public/leads handler uses get_service_db; the admin list
-- endpoint is gated by MARKETING_LEADS_ADMIN_TOKEN, not by a tenant JWT.
-- ============================================================================

CREATE TABLE marketing_leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT NOT NULL,
    business_name   TEXT NOT NULL,
    email           CITEXT NOT NULL,
    team_size       TEXT NOT NULL
                    CHECK (team_size IN ('solo', 'team', 'business', 'enterprise')),
    source          TEXT NOT NULL DEFAULT 'marketing-signup',
    ip_hint         INET,
    user_agent      TEXT,
    notified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_marketing_leads_created_at
    ON marketing_leads (created_at DESC);

CREATE INDEX idx_marketing_leads_email_created
    ON marketing_leads (email, created_at DESC);

-- No RLS: platform table, no tenant key. Service role only.
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_leads TO harboriq_service;
REVOKE ALL ON TABLE marketing_leads FROM harboriq_app;

COMMENT ON TABLE marketing_leads IS
    'Platform marketing / trial signup leads from the public GTM site. '
    'SERVICE ROLE ONLY (harboriq_service). No tenant_id / no RLS by design — '
    'leads predate company creation. App role deliberately revoked.';
