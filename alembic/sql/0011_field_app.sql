-- HarborIQ v2 — Offline-Capable Mobile Field App (Phase 12).
-- Executed verbatim by Alembic migration 0011_field_app.
--
-- ============================================================================
-- JOB ATTACHMENTS — photos + digital signatures captured in the field
-- ============================================================================
-- Storage decision: no S3/blob-storage convention exists anywhere yet in this
-- codebase (Phase 8's invoice PDFs are generated on demand and streamed, never
-- persisted to disk/object storage — see app/services/invoice_pdf.py). Rather
-- than introduce a new external dependency (S3/MinIO/GCS credentials, bucket
-- lifecycle policy, local dev parity) for what is, for now, a modest volume of
-- phone-camera photos and signature traces, `data` stores base64-encoded bytes
-- directly in the row. This is an explicit, documented MVP fallback (see
-- README, "Field capture (Phase 12)") — the natural next step once photo
-- volume/size grows is an object-storage-backed `storage_path` column instead
-- (the column exists below, unused for now, so that migration is additive:
-- backfill `storage_path`, stop writing `data`, no schema change needed).
CREATE TYPE job_attachment_kind AS ENUM ('photo', 'signature', 'other');

CREATE TABLE job_attachments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id    UUID NOT NULL REFERENCES companies(id),
    job_id        UUID NOT NULL,
    kind          job_attachment_kind NOT NULL,
    -- Present-day storage: base64 of the raw bytes. NULL once/if a future
    -- phase moves this row to object storage (see note above).
    data          TEXT,
    -- Reserved for a future object-storage-backed implementation; unused
    -- (always NULL) as of this phase.
    storage_path  TEXT,
    content_type  TEXT NOT NULL DEFAULT 'image/jpeg',
    -- Client-generated key from the offline-sync queue (see README, "Offline
    -- queue idempotency"). Uploading the same queued action twice (e.g. a
    -- retry after a dropped response) must not create two attachment rows.
    idempotency_key TEXT,
    uploaded_by   UUID NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_job_attachments_job
        FOREIGN KEY (company_id, job_id)
        REFERENCES jobs (company_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_job_attachments_has_payload
        CHECK (data IS NOT NULL OR storage_path IS NOT NULL)
);

CREATE INDEX idx_job_attachments_job ON job_attachments (company_id, job_id);
-- Idempotent-replay lookup: NULL keys (attachments created outside the
-- offline-sync path, e.g. directly from the admin UI) are excluded, so only
-- queue-originated uploads participate in the uniqueness check.
CREATE UNIQUE INDEX uq_job_attachments_idempotency
    ON job_attachments (company_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- ============================================================================
-- JOB TIME ENTRIES — technician clock in/out per job (DockMaster parity)
-- ============================================================================
CREATE TABLE job_time_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    job_id          UUID NOT NULL,
    technician_id   UUID NOT NULL REFERENCES users(id),
    clocked_in_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    clocked_out_at  TIMESTAMPTZ,
    -- Same offline-sync idempotency story as job_attachments above.
    idempotency_key TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_job_time_entries_job
        FOREIGN KEY (company_id, job_id)
        REFERENCES jobs (company_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_job_time_entries_clockout_after_clockin
        CHECK (clocked_out_at IS NULL OR clocked_out_at >= clocked_in_at)
);

CREATE INDEX idx_job_time_entries_job ON job_time_entries (company_id, job_id);
-- Enforces "can't clock in twice without clocking out" at the database layer,
-- not just in the service layer: at most one OPEN (clocked_out_at IS NULL)
-- entry per (job, technician) at a time.
CREATE UNIQUE INDEX uq_job_time_entries_one_open_per_tech_job
    ON job_time_entries (company_id, job_id, technician_id)
    WHERE clocked_out_at IS NULL;
CREATE UNIQUE INDEX uq_job_time_entries_idempotency
    ON job_time_entries (company_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- ============================================================================
-- ROW-LEVEL SECURITY — same backstop as every other tenant table
-- ============================================================================
ALTER TABLE job_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_attachments FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_job_attachments ON job_attachments
    USING (company_id::text = current_setting('app.current_company_id', true));

ALTER TABLE job_time_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_time_entries FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_job_time_entries ON job_time_entries
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- GRANTS (0001's GRANT ... ON ALL TABLES only covered tables existing then)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON job_attachments TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON job_attachments TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON job_time_entries TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON job_time_entries TO harboriq_service;
