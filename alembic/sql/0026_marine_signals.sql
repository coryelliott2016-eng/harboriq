CREATE TABLE marine_signal_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN (
        'weather', 'environment', 'safety_recall', 'regulation',
        'season', 'training', 'fuel', 'market'
    )),
    source_url TEXT NOT NULL,
    feed_url TEXT NOT NULL,
    terms_url TEXT NOT NULL,
    terms_reviewed_at TIMESTAMPTZ NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    last_checked_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_marine_signal_sources_company_id UNIQUE (company_id, id)
);

CREATE TABLE marine_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_id UUID NOT NULL,
    external_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN (
        'weather', 'environment', 'safety_recall', 'regulation',
        'season', 'training', 'fuel', 'market'
    )),
    title TEXT NOT NULL,
    source_content TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    why_it_matters TEXT NOT NULL DEFAULT '',
    suggested_action TEXT NOT NULL DEFAULT '',
    citation_url TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    effective_until TIMESTAMPTZ,
    geography TEXT NOT NULL DEFAULT '',
    uncertainty TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'urgent')),
    status TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (status IN ('needs_review', 'published', 'stale', 'superseded')),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_marine_signals_company_id UNIQUE (company_id, id),
    CONSTRAINT uq_marine_signals_source_external UNIQUE (company_id, source_id, external_id),
    CONSTRAINT fk_marine_signals_source FOREIGN KEY (company_id, source_id)
        REFERENCES marine_signal_sources(company_id, id) ON DELETE CASCADE
);

CREATE TABLE marine_signal_profiles (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    service_area TEXT NOT NULL DEFAULT '',
    specialties TEXT[] NOT NULL DEFAULT '{}',
    interests TEXT[] NOT NULL DEFAULT '{}',
    digest_email TEXT,
    digest_enabled BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_marine_signal_digest_email CHECK (
        NOT digest_enabled OR digest_email IS NOT NULL
    )
);

CREATE TABLE marine_signal_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback TEXT NOT NULL CHECK (
        feedback IN ('saved', 'dismissed', 'flagged', 'useful', 'acted')
    ),
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_marine_signal_feedback_company_signal_user
        UNIQUE (company_id, signal_id, user_id),
    CONSTRAINT fk_marine_signal_feedback_signal FOREIGN KEY (company_id, signal_id)
        REFERENCES marine_signals(company_id, id) ON DELETE CASCADE
);

CREATE INDEX ix_marine_signal_sources_enabled
    ON marine_signal_sources (company_id, enabled);
CREATE INDEX ix_marine_signals_status_published
    ON marine_signals (company_id, status, published_at DESC);
CREATE INDEX ix_marine_signals_expiration
    ON marine_signals (effective_until) WHERE status = 'published';
CREATE INDEX ix_marine_signal_feedback_company_feedback
    ON marine_signal_feedback (company_id, feedback);

ALTER TABLE marine_signal_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE marine_signal_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_marine_signal_sources ON marine_signal_sources
    USING (company_id::text = current_setting('app.current_company_id', true))
    WITH CHECK (company_id::text = current_setting('app.current_company_id', true));

ALTER TABLE marine_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE marine_signals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_marine_signals ON marine_signals
    USING (company_id::text = current_setting('app.current_company_id', true))
    WITH CHECK (company_id::text = current_setting('app.current_company_id', true));

ALTER TABLE marine_signal_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE marine_signal_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_marine_signal_profiles ON marine_signal_profiles
    USING (company_id::text = current_setting('app.current_company_id', true))
    WITH CHECK (company_id::text = current_setting('app.current_company_id', true));

ALTER TABLE marine_signal_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE marine_signal_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_marine_signal_feedback ON marine_signal_feedback
    USING (company_id::text = current_setting('app.current_company_id', true))
    WITH CHECK (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON marine_signal_sources TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON marine_signals TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON marine_signal_profiles TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON marine_signal_feedback TO harboriq_app;
