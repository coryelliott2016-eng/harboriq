-- HarborIQ v2 — Inventory, Parts & Vendor Integration (Phase 13).
-- Executed verbatim by Alembic migration 0012_inventory_procurement.
--
-- ============================================================================
-- INVENTORY ITEMS — SKU becomes a real per-tenant unique key (barcode lookup)
-- ============================================================================
-- `sku` (migration 0001) has always been nullable and had no uniqueness
-- constraint -- fine while the only writer was the atomic `POST /inventory/use`
-- decrement, which never needed to look an item up BY sku. This phase adds
-- `GET /inventory/lookup?sku=...` (the barcode-scanner-style workflow), so a
-- duplicate SKU inside one tenant would silently make that lookup ambiguous.
-- A partial unique index (excluding NULL) preserves "SKU is optional" for
-- items that don't have one yet while still guaranteeing "if two items in the
-- same company both have a SKU, it's the same rule as a UPC/barcode: unique."
CREATE UNIQUE INDEX uq_inventory_items_company_sku
    ON inventory_items (company_id, sku)
    WHERE sku IS NOT NULL;

-- ============================================================================
-- VENDORS
-- ============================================================================
CREATE TABLE vendors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    name            TEXT NOT NULL,
    contact_email   TEXT,
    contact_phone   TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vendors_company ON vendors (company_id);

ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_vendors ON vendors
    USING (company_id::text = current_setting('app.current_company_id', true));

-- Optional "last/default vendor" for an item, used by the reorder-suggestions
-- endpoint to group suggested reorders by vendor so a generated draft PO
-- already has a vendor picked instead of forcing the operator to look one up
-- per line. Nullable: an item with no vendor history yet is grouped under
-- an "unassigned vendor" bucket by the service layer, not blocked. Added
-- after `vendors` exists so the FK target is already in place.
ALTER TABLE inventory_items
    ADD COLUMN default_vendor_id UUID REFERENCES vendors(id);

-- ============================================================================
-- PURCHASE ORDERS + LINE ITEMS
-- ============================================================================
-- Status transitions are enforced in app/services/state_machines.py
-- (PurchaseOrderSM), mirroring JobSM/InvoiceSM: draft -> submitted -> received,
-- with cancellation allowed from draft or submitted (not from received --
-- stock has already moved by then, matching invoices.py's terminal-state
-- convention for a completed money/stock movement).
CREATE TYPE purchase_order_status AS ENUM ('draft', 'submitted', 'received', 'cancelled');

CREATE TABLE purchase_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id),
    vendor_id       UUID NOT NULL REFERENCES vendors(id),
    status          purchase_order_status NOT NULL DEFAULT 'draft',
    created_by      UUID NOT NULL REFERENCES users(id),
    submitted_at    TIMESTAMPTZ,
    received_at     TIMESTAMPTZ,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_purchase_orders_company ON purchase_orders (company_id, status);
-- Target of the line items' composite FK below, matching the
-- uq_jobs_company_id / job_attachments convention (migration 0003/0011).
ALTER TABLE purchase_orders ADD CONSTRAINT uq_purchase_orders_company_id UNIQUE (company_id, id);

CREATE TABLE purchase_order_line_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL REFERENCES companies(id),
    purchase_order_id  UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    inventory_item_id  UUID NOT NULL REFERENCES inventory_items(id),
    quantity_ordered    INTEGER NOT NULL CHECK (quantity_ordered > 0),
    -- Incremented (possibly across multiple partial receipts) by
    -- app/services/purchase_orders.py under the SAME FOR UPDATE-guarded
    -- pattern app/services/inventory.py already established for
    -- quantity_on_hand. Never exceeds quantity_ordered.
    quantity_received  INTEGER NOT NULL DEFAULT 0 CHECK (quantity_received >= 0),
    unit_cost           NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_po_line_received_lte_ordered
        CHECK (quantity_received <= quantity_ordered),
    CONSTRAINT fk_po_line_items_po
        FOREIGN KEY (company_id, purchase_order_id)
        REFERENCES purchase_orders (company_id, id) ON DELETE CASCADE
);

CREATE INDEX idx_po_line_items_po ON purchase_order_line_items (company_id, purchase_order_id);

ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_purchase_orders ON purchase_orders
    USING (company_id::text = current_setting('app.current_company_id', true));

ALTER TABLE purchase_order_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_line_items FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_po_line_items ON purchase_order_line_items
    USING (company_id::text = current_setting('app.current_company_id', true));

-- ============================================================================
-- GRANTS (0001's GRANT ... ON ALL TABLES only covered tables existing then)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON vendors TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON vendors TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_orders TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_orders TO harboriq_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_order_line_items TO harboriq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_order_line_items TO harboriq_service;
