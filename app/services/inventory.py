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

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services.crud import NotFound


class InsufficientStock(Exception):
    pass


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
