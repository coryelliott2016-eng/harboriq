ALTER TABLE marketing_leads
    ADD COLUMN marketing_email_opt_in BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN marketing_email_consent_at TIMESTAMPTZ,
    ADD COLUMN marketing_email_consent_version TEXT,
    ADD COLUMN marketing_email_consent_method TEXT,
    DROP COLUMN ip_hint,
    DROP COLUMN user_agent,
    ADD CONSTRAINT ck_marketing_leads_email_consent_metadata CHECK (
        (
            marketing_email_opt_in
            AND marketing_email_consent_at IS NOT NULL
            AND marketing_email_consent_version IS NOT NULL
            AND marketing_email_consent_method IS NOT NULL
        )
        OR (
            NOT marketing_email_opt_in
            AND marketing_email_consent_at IS NULL
            AND marketing_email_consent_version IS NULL
            AND marketing_email_consent_method IS NULL
        )
    );

COMMENT ON COLUMN marketing_leads.marketing_email_opt_in IS
    'Affirmative, optional permission for HarborIQ email marketing; false is not permission.';
