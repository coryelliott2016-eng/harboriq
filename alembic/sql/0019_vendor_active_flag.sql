-- Phase 17 Area F: vendor deactivate/archive.
--
-- Vendors are never hard-deleted (purchase_orders.vendor_id references them
-- for the life of the PO's audit trail). Instead an owner/admin can mark a
-- vendor inactive; it disappears from the default vendor list and from
-- "choose a vendor for a new PO" pickers, but GET /vendors/{id} keeps
-- working unconditionally so historical purchase orders can still resolve
-- and render the vendor they were actually placed with.
ALTER TABLE vendors
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

-- Default vendor list view (active-only) is the hot path; keep it fast as
-- the vendor table grows.
CREATE INDEX IF NOT EXISTS idx_vendors_company_active
    ON vendors (company_id, is_active);
