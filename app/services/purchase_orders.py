"""Purchase orders — draft/submit/receive against a vendor (Phase 13).

Status is never written directly: `submit_purchase_order`/`receive_purchase_order`
reload the row `FOR UPDATE`, hand the current and target values to
`app.services.state_machines.PurchaseOrderSM`, and only then write — the same
discipline `app.services.jobs.set_status`/`app.services.invoices` already use.

Receiving increments `inventory_items.quantity_on_hand` through
`app.services.inventory.receive_inventory_atomic`, the SAME kind of
`FOR UPDATE`-guarded conditional UPDATE `app.services.inventory` already uses
to DEDUCT stock on `POST /inventory/use` — this module does not, and must not,
write `quantity_on_hand` any other way.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, ValidationFailed
from app.services.inventory import receive_inventory_atomic
from app.services.state_machines import IllegalTransition, PurchaseOrderSM


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "purchase_orders_vendor_id_fkey" in detail or "fk_purchase_orders_vendor" in detail:
        return NotFound("vendor not found")
    if "purchase_order_line_items_inventory_item_id_fkey" in detail:
        return NotFound("inventory item not found")
    if "ck_po_line_qty_ordered_gt0" in detail:
        return ValidationFailed("quantity_ordered must be positive")
    return Conflict("purchase order violates a database constraint")


def _require_row(db: Session, table: str, row_id: uuid.UUID, label: str) -> None:
    found = db.execute(
        text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}  # noqa: S608
    ).first()
    if found is None:
        raise NotFound(f"{label} {row_id} not found")


# ---------------------------------------------------------------------------
# create (draft) — with line items in the same transaction
# ---------------------------------------------------------------------------
def create_draft(
    db: Session,
    company_id: uuid.UUID,
    created_by: uuid.UUID,
    vendor_id: uuid.UUID,
    line_items: list[dict[str, Any]],
    *,
    notes: str | None = None,
) -> Row:
    """Create a `draft` purchase order with its line items.

    A draft with zero line items is refused — there is nothing to submit or
    receive against, and an empty PO is almost certainly a mistake rather
    than an intentional placeholder (unlike, say, a job, which legitimately
    starts empty before line items are billed as work happens).
    """
    if not line_items:
        raise ValidationFailed("a purchase order needs at least one line item")

    try:
        with tenant_context(db, company_id):
            _require_row(db, "vendors", vendor_id, "vendor")
            for li in line_items:
                _require_row(db, "inventory_items", li["inventory_item_id"], "inventory item")

            po_row = db.execute(
                text(
                    """
                    INSERT INTO purchase_orders (company_id, vendor_id, created_by, notes)
                    VALUES (:company_id, :vendor_id, :created_by, :notes)
                    RETURNING *
                    """
                ),
                {
                    "company_id": company_id,
                    "vendor_id": vendor_id,
                    "created_by": created_by,
                    "notes": notes,
                },
            ).first()

            for li in line_items:
                db.execute(
                    text(
                        """
                        INSERT INTO purchase_order_line_items
                            (company_id, purchase_order_id, inventory_item_id,
                             quantity_ordered, unit_cost)
                        VALUES
                            (:company_id, :po_id, :item_id, :qty, :unit_cost)
                        """
                    ),
                    {
                        "company_id": company_id,
                        "po_id": po_row.id,
                        "item_id": li["inventory_item_id"],
                        "qty": li["quantity_ordered"],
                        "unit_cost": li.get("unit_cost", Decimal("0")),
                    },
                )
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc

    return get(db, company_id, po_row.id)


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------
def get(db: Session, company_id: uuid.UUID, po_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        po = db.execute(
            text("SELECT * FROM purchase_orders WHERE id = :id"), {"id": po_id}
        ).first()
        if po is None:
            raise NotFound(f"purchase order {po_id} not found")
        lines = db.execute(
            text(
                """
                SELECT * FROM purchase_order_line_items
                 WHERE purchase_order_id = :po_id
                 ORDER BY created_at
                """
            ),
            {"po_id": po_id},
        ).all()
    return _with_lines(po, lines)


def list_purchase_orders(
    db: Session, company_id: uuid.UUID, *, status: str | None = None
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id}
    if status:
        clauses = " AND status = CAST(:status AS purchase_order_status)"
        params["status"] = status

    with tenant_context(db, company_id):
        pos = db.execute(
            text(
                f"""
                SELECT * FROM purchase_orders
                 WHERE company_id = :cid {clauses}
                 ORDER BY created_at DESC
                """
            ),
            params,
        ).all()
        if not pos:
            return []
        lines = db.execute(
            text(
                """
                SELECT * FROM purchase_order_line_items
                 WHERE purchase_order_id = ANY(:ids)
                 ORDER BY created_at
                """
            ),
            {"ids": [p.id for p in pos]},
        ).all()

    lines_by_po: dict[uuid.UUID, list[Row]] = {}
    for line in lines:
        lines_by_po.setdefault(line.purchase_order_id, []).append(line)
    return [_with_lines(po, lines_by_po.get(po.id, [])) for po in pos]


def _with_lines(po: Row, lines: list[Row]) -> dict[str, Any]:
    return dict(po._mapping) | {"line_items": [dict(li._mapping) for li in lines]}


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------
def submit(db: Session, company_id: uuid.UUID, po_id: uuid.UUID) -> Row:
    """Move a `draft` PO to `submitted` — the human commitment point.

    This is deliberately the only action that represents "we told the vendor
    we want this" — nothing in this codebase calls it automatically (see the
    README's reorder-suggestions write-up for the full reasoning).
    """
    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status FROM purchase_orders WHERE id = :id FOR UPDATE"),
            {"id": po_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"purchase order {po_id} not found")
        try:
            PurchaseOrderSM.assert_transition(current.status, "submitted")
        except IllegalTransition:
            db.rollback()
            raise

        db.execute(
            text(
                """
                UPDATE purchase_orders
                   SET status = 'submitted', submitted_at = now(), updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": po_id},
        )
        db.commit()
    return get(db, company_id, po_id)


# ---------------------------------------------------------------------------
# receive (full or partial)
# ---------------------------------------------------------------------------
def receive(
    db: Session,
    company_id: uuid.UUID,
    po_id: uuid.UUID,
    receipts: list[dict[str, Any]],
) -> Row:
    """Record actual received quantities per line item; may be partial.

    `receipts` is `[{"line_item_id": ..., "quantity": ...}, ...]`. Every named
    line's `quantity_received` is incremented by the given amount (never set
    outright, so two separate partial receipts against the same line
    correctly accumulate) and each corresponding inventory item's
    `quantity_on_hand` is incremented through the SAME guarded writer
    `app.services.inventory` already uses to decrement it. The PO moves to
    `received` regardless of whether every line is fully fulfilled — DockMaster/
    ServiceTitan-style procurement treats "received" as "this shipment event
    happened", not "every unit ordered arrived"; a still-short line is visible
    via `quantity_received < quantity_ordered` on the line itself, and a
    still-short item will keep surfacing on `GET /inventory/reorder-suggestions`
    if it's still below its reorder point, which is the honest signal to
    generate a follow-up PO rather than a hidden second meaning bolted onto
    this one's status.
    """
    if not receipts:
        raise ValidationFailed("at least one line item receipt is required")

    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status FROM purchase_orders WHERE id = :id FOR UPDATE"),
            {"id": po_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"purchase order {po_id} not found")
        try:
            PurchaseOrderSM.assert_transition(current.status, "received")
        except IllegalTransition:
            db.rollback()
            raise

        for receipt in receipts:
            qty = receipt["quantity"]
            if qty <= 0:
                db.rollback()
                raise ValidationFailed("received quantity must be positive")

            line = db.execute(
                text(
                    """
                    SELECT * FROM purchase_order_line_items
                     WHERE id = :id AND purchase_order_id = :po_id
                     FOR UPDATE
                    """
                ),
                {"id": receipt["line_item_id"], "po_id": po_id},
            ).first()
            if line is None:
                db.rollback()
                raise NotFound(
                    f"line item {receipt['line_item_id']} not found on this purchase order"
                )
            if line.quantity_received + qty > line.quantity_ordered:
                db.rollback()
                raise ValidationFailed(
                    f"cannot receive {qty} more of line {line.id}: "
                    f"only {line.quantity_ordered - line.quantity_received} still outstanding"
                )

            db.execute(
                text(
                    """
                    UPDATE purchase_order_line_items
                       SET quantity_received = quantity_received + :qty
                     WHERE id = :id
                    """
                ),
                {"id": line.id, "qty": qty},
            )
            # Same guarded writer used by POST /inventory/use, just adding.
            receive_inventory_atomic(db, company_id, line.inventory_item_id, qty)

        db.execute(
            text(
                """
                UPDATE purchase_orders
                   SET status = 'received', received_at = now(), updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": po_id},
        )
        db.commit()
    return get(db, company_id, po_id)


def cancel(db: Session, company_id: uuid.UUID, po_id: uuid.UUID) -> Row:
    """Cancel a `draft` or `submitted` PO. Refused once `received`."""
    with tenant_context(db, company_id):
        current = db.execute(
            text("SELECT status FROM purchase_orders WHERE id = :id FOR UPDATE"),
            {"id": po_id},
        ).first()
        if current is None:
            db.rollback()
            raise NotFound(f"purchase order {po_id} not found")
        try:
            PurchaseOrderSM.assert_transition(current.status, "cancelled")
        except IllegalTransition:
            db.rollback()
            raise

        db.execute(
            text("UPDATE purchase_orders SET status = 'cancelled', updated_at = now() WHERE id = :id"),
            {"id": po_id},
        )
        db.commit()
    return get(db, company_id, po_id)


# ---------------------------------------------------------------------------
# reorder-suggestion -> draft PO generation (one-click, still a draft)
# ---------------------------------------------------------------------------
def generate_draft_from_suggestions(
    db: Session,
    company_id: uuid.UUID,
    created_by: uuid.UUID,
    vendor_id: uuid.UUID,
    item_ids: list[uuid.UUID],
) -> Row:
    """Build ONE draft PO for `vendor_id` covering the named items.

    Each line orders enough to bring `quantity_on_hand` back up to
    `reorder_point` (the simplest honest default — "restock to the line you
    said you never want to cross" — rather than guessing at a larger economic
    order quantity this platform has no sales-velocity model to justify yet).
    Still just a `draft`: see this module's `receive`/`submit` docstrings and
    the README for why generating the PO is one click but SENDING it to a
    real vendor is deliberately not.
    """
    if not item_ids:
        raise ValidationFailed("select at least one item to reorder")

    with tenant_context(db, company_id):
        items = db.execute(
            text(
                """
                SELECT id, reorder_point, quantity_on_hand, unit_cost FROM inventory_items
                 WHERE id = ANY(:ids) AND quantity_on_hand < reorder_point
                """
            ),
            {"ids": item_ids},
        ).all()

    if not items:
        raise ValidationFailed(
            "none of the selected items are currently below their reorder point"
        )

    line_items = [
        {
            "inventory_item_id": item.id,
            "quantity_ordered": item.reorder_point - item.quantity_on_hand,
            "unit_cost": item.unit_cost,
        }
        for item in items
    ]
    return create_draft(db, company_id, created_by, vendor_id, line_items)


__all__ = [
    "cancel",
    "create_draft",
    "generate_draft_from_suggestions",
    "get",
    "list_purchase_orders",
    "receive",
    "submit",
]
