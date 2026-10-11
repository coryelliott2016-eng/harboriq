-- Historical contact permission is unknown: do not infer or backfill consent.
ALTER TABLE marketing_leads
    ADD COLUMN contact_consent_at TIMESTAMPTZ,
    ADD COLUMN consent_version TEXT,
    ADD COLUMN marketing_consent BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN marketing_consent_at TIMESTAMPTZ;

COMMENT ON COLUMN marketing_leads.contact_consent_at IS
    'Latest explicit permission to respond to a contact request; NULL means unknown.';
COMMENT ON COLUMN marketing_leads.consent_version IS
    'Server-controlled version of the contact consent disclosure; NULL for legacy leads.';
COMMENT ON COLUMN marketing_leads.marketing_consent IS
    'Independent optional marketing permission; false unless explicitly selected.';
COMMENT ON COLUMN marketing_leads.marketing_consent_at IS
    'Latest explicit marketing opt-in timestamp; cleared when permission is withdrawn.';
