"""Inventory — atomic, concurrency-safe stock deduction.

Replaces the original read-check-write pattern that oversold parts under
concurrency. Uses a single conditional UPDATE so two concurrent claims on the
last unit cannot both succeed.

This is the ONLY writer of `quantity_on_hand`. When the caller names a job, the
matching billable line is appended in the SAME transaction as the deduction, so
the shop can never have taken a part off the shelf without it appearing on the
work order (or vice versa).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import Conflict, NotFound, assignments, like_term


class InsufficientStock(Exception):
    pass


#: Columns settable/updatable directly (i.e. everything except the
#: quantity_on_hand/low_stock_alerted pair, which only ever move through the
#: guarded writers in this module -- see the module docstring).
UPDATABLE_COLUMNS = frozenset(
    {"sku", "name", "unit_cost", "retail_price", "reorder_point", "default_vendor_id"}
)
_INSERT_COLUMNS = sorted(UPDATABLE_COLUMNS)

_INSERT = text(
    f"""
    INSERT INTO inventory_items (company_id, {", ".join(_INSERT_COLUMNS)})
    VALUES (:company_id, {", ".join(f":{c}" for c in _INSERT_COLUMNS)})
    RETURNING *
    """
)


def _map_integrity_error(exc: IntegrityError) -> Exception:
    detail = str(exc.orig)
    if "uq_inventory_items_company_sku" in detail:
        return Conflict("an inventory item with this SKU already exists")
    if "default_vendor_id" in detail:
        return NotFound("vendor not found")
    return Conflict("inventory item violates a database constraint")


def create(db: Session, company_id: uuid.UUID, data: dict[str, Any]) -> Row:
    """Create an inventory item. `quantity_on_hand` always starts at 0 here --
    stock is only ever added by receiving a purchase order (see
    `receive_purchase_order`), never typed in directly, so every unit on the
    shelf always traces back to a real receipt.
    """
    params = {"company_id": company_id} | {c: data.get(c) for c in _INSERT_COLUMNS}
    try:
        with tenant_context(db, company_id):
            row = db.execute(_INSERT, params).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    return row


def get(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> Row:
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM inventory_items WHERE id = :id"), {"id": item_id}
        ).first()
    if row is None:
        raise NotFound(f"inventory item {item_id} not found")
    return row


def list_items(
    db: Session,
    company_id: uuid.UUID,
    *,
    search: str | None = None,
    low_stock_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    clauses = ""
    params: dict[str, Any] = {"cid": company_id, "limit": limit, "offset": offset}
    if search:
        clauses += " AND (name ILIKE :term OR sku ILIKE :term)"
        params["term"] = like_term(search)
    if low_stock_only:
        clauses += " AND quantity_on_hand < reorder_point"

    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM inventory_items
                     WHERE company_id = :cid {clauses}
                     ORDER BY name
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).all()
        )


def lookup_by_sku(db: Session, company_id: uuid.UUID, sku: str) -> Row:
    """Fast single-item lookup by SKU -- the barcode-scanner-style workflow.

    Relies on `uq_inventory_items_company_sku` (migration 0012) for both
    correctness (at most one match) and speed (index lookup, not a scan).
    """
    with tenant_context(db, company_id):
        row = db.execute(
            text("SELECT * FROM inventory_items WHERE sku = :sku"), {"sku": sku}
        ).first()
    if row is None:
        raise NotFound(f"no inventory item with SKU {sku!r}")
    return row


def update(
    db: Session, company_id: uuid.UUID, item_id: uuid.UUID, changes: dict[str, Any]
) -> Row:
    if not changes:
        return get(db, company_id, item_id)

    # `inventory_items` (migration 0001) has no `updated_at` column -- only
    # `created_at` -- unlike most other tenant tables. Not adding one here;
    # this is a pre-existing schema shape from before this phase, not
    # something Phase 13 should silently change underneath every existing
    # row and query.
    statement = text(
        f"""
        UPDATE inventory_items
           SET {assignments(changes, UPDATABLE_COLUMNS)}
         WHERE id = :id
        RETURNING *
        """
    )
    try:
        with tenant_context(db, company_id):
            row = db.execute(statement, changes | {"id": item_id}).first()
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _map_integrity_error(exc) from exc
    if row is None:
        raise NotFound(f"inventory item {item_id} not found")
    return row


def _record_part_line(
    db: Session, company_id: uuid.UUID, job_id: uuid.UUID, item: Row, quantity: int
) -> None:
    """Append the committed `part` line for a stock movement.

    Priced at the item's retail price captured now: a later price change must
    not silently re-price work already done.
    """
    db.execute(
        text(
            """
            INSERT INTO job_line_items
                (company_id, job_id, kind, description, inventory_item_id,
                 quantity, unit_price, inventory_committed)
            VALUES
                (:company_id, :job_id, 'part', :description, :item_id,
                 :quantity, :unit_price, true)
            """
        ),
        {
            "company_id": company_id,
            "job_id": job_id,
            "description": item.name,
            "item_id": item.id,
            "quantity": quantity,
            "unit_price": item.retail_price,
        },
    )


def use_inventory_part_atomic(
    db: Session,
    company_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: int,
    *,
    job_id: uuid.UUID | None = None,
) -> int:
    """Deduct `quantity` of `item_id` atomically. Returns the new on-hand count.

    With `job_id`, also bills the part to that work order in the same
    transaction.

    Raises ValueError if quantity <= 0, NotFound if `job_id` is not a job in
    this tenant, and InsufficientStock if there is not enough stock (or the item
    is not found in this tenant).
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    with tenant_context(db, company_id):
        if job_id is not None:
            job = db.execute(
                text("SELECT 1 FROM jobs WHERE id = :id"), {"id": job_id}
            ).first()
            if job is None:
                db.rollback()
                raise NotFound(f"job {job_id} not found")

        result = db.execute(
            text(
                """
                UPDATE inventory_items
                   SET quantity_on_hand = quantity_on_hand - :qty,
                       low_stock_alerted = (quantity_on_hand - :qty < reorder_point)
                 WHERE id = :id
                   AND company_id::text = current_setting('app.current_company_id')
                   AND quantity_on_hand >= :qty
                RETURNING id, name, retail_price, quantity_on_hand
                """
            ),
            {"id": item_id, "qty": quantity},
        )
        row = result.first()

        if row is None:
            db.rollback()
            raise InsufficientStock(
                f"insufficient stock for item {item_id} (requested {quantity})"
            )

        if job_id is not None:
            _record_part_line(db, company_id, job_id, row, quantity)

    db.commit()
    return int(row.quantity_on_hand)


def receive_inventory_atomic(
    db: Session, company_id: uuid.UUID, item_id: uuid.UUID, quantity: int
) -> int:
    """Increment `quantity_on_hand` atomically. Returns the new on-hand count.

    The SAME kind of guarded conditional UPDATE as `use_inventory_part_atomic`
    above (this module's docstring: the ONLY writer of `quantity_on_hand`),
    just adding instead of subtracting -- so a purchase-order receipt and a
    job's part usage can never race into a lost update on the same row.
    Resets `low_stock_alerted` back to false once the receipt clears the
    reorder point, mirroring the decrement path's own alert bookkeeping.

    Called from `app.services.purchase_orders.receive_purchase_order` inside
    that function's own transaction/tenant_context -- this does not commit,
    so a partial receipt across several line items stays one atomic unit
    together with the purchase order's own status/line updates.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    result = db.execute(
        text(
            """
            UPDATE inventory_items
               SET quantity_on_hand = quantity_on_hand + :qty,
                   low_stock_alerted = (quantity_on_hand + :qty < reorder_point)
             WHERE id = :id
               AND company_id::text = current_setting('app.current_company_id')
            RETURNING id, quantity_on_hand
            """
        ),
        {"id": item_id, "qty": quantity},
    )
    row = result.first()
    if row is None:
        raise NotFound(f"inventory item {item_id} not found")
    return int(row.quantity_on_hand)


# ---------------------------------------------------------------------------
# Low-stock reorder suggestions -- read-only signal, NOT automated ordering.
#
# Deliberate scope boundary (see README "Inventory, parts & vendors" and the
# phase spec): this only ever SUGGESTS. Generating a draft PO from a
# suggestion (`generate_reorder_draft_po` / `app.services.purchase_orders`)
# still leaves it in `draft` status -- a human must explicitly submit it
# (`POST /purchase-orders/{id}/submit`) before it means anything to a real
# vendor. Real money and real vendor relationships are not something this
# platform will ever commit to unattended.
# ---------------------------------------------------------------------------
def reorder_suggestions(db: Session, company_id: uuid.UUID) -> list[Row]:
    """Items below their reorder point, best default-vendor-grouping first.

    `default_vendor_id` may be NULL (no purchasing history yet); the caller
    groups those under an explicit "no default vendor" bucket rather than
    dropping them from the list -- a part still needs reordering even when
    nobody has told the system who to buy it from yet.
    """
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM inventory_items
                     WHERE company_id = :cid AND quantity_on_hand < reorder_point
                     ORDER BY default_vendor_id NULLS LAST, name
                    """
                ),
                {"cid": company_id},
            ).all()
        )
