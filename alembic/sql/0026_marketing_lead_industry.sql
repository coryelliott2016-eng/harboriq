ALTER TABLE marketing_leads
    ADD COLUMN industry TEXT,
    ADD CONSTRAINT ck_marketing_leads_industry CHECK (
        industry IS NULL OR industry IN (
            'marina_or_boatyard',
            'marine_towing_or_assistance',
            'commercial_fishing',
            'recreational_fishing',
            'marine_repair',
            'yacht_or_charter_operations',
            'boat_owner',
            'dealer_or_broker',
            'supplier_or_manufacturer',
            'surveyor_or_insurance',
            'commercial_fleet',
            'other_marine_business'
        )
    );

CREATE INDEX idx_marketing_leads_industry ON marketing_leads (industry);
