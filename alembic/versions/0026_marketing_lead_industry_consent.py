"""Classify public leads and record explicit email marketing consent."""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE marketing_leads
        ADD COLUMN industry TEXT NOT NULL DEFAULT 'other',
        ADD COLUMN business_need TEXT NOT NULL DEFAULT '',
        ADD COLUMN product_interest TEXT NOT NULL DEFAULT 'operations',
        ADD COLUMN email_marketing_opt_in BOOLEAN NOT NULL DEFAULT false,
        ADD COLUMN contact_requested BOOLEAN NOT NULL DEFAULT true,
        ADD COLUMN email_marketing_consented_at TIMESTAMPTZ,
        ADD COLUMN email_marketing_consent_version TEXT,
        ADD CONSTRAINT ck_marketing_leads_industry CHECK (industry IN (
            'marinas', 'marine-towing', 'commercial-fishing', 'recreational-fishing',
            'marine-service', 'charters', 'boat-owners', 'dealers', 'suppliers',
            'surveyors', 'commercial-fleets', 'other'
        )),
        ADD CONSTRAINT ck_marketing_leads_product_interest
            CHECK (product_interest IN ('operations', 'ai', 'partnership')),
        ADD CONSTRAINT ck_marketing_leads_business_need CHECK (length(business_need) <= 2000),
        ADD CONSTRAINT ck_marketing_leads_email_consent CHECK (
            (email_marketing_opt_in AND email_marketing_consented_at IS NOT NULL
                AND email_marketing_consent_version IS NOT NULL) OR
            (NOT email_marketing_opt_in AND email_marketing_consented_at IS NULL
                AND email_marketing_consent_version IS NULL)
        )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE marketing_leads
        DROP COLUMN email_marketing_consent_version,
        DROP COLUMN email_marketing_consented_at,
        DROP COLUMN contact_requested,
        DROP COLUMN email_marketing_opt_in,
        DROP COLUMN product_interest,
        DROP COLUMN business_need,
        DROP COLUMN industry
    """)
