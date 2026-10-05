CREATE TABLE marine_signal_digest_deliveries (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('sending', 'sent')),
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ,
    PRIMARY KEY (company_id, week_start)
);

ALTER TABLE marine_signal_digest_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE marine_signal_digest_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_marine_signal_digest_deliveries
    ON marine_signal_digest_deliveries
    USING (company_id::text = current_setting('app.current_company_id', true))
    WITH CHECK (company_id::text = current_setting('app.current_company_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE
    ON marine_signal_digest_deliveries TO harboriq_app;
