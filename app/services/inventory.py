"""Inventory — atomic, concurrency-safe stock deduction.

Replaces the original read-check-write pattern that oversold parts under
concurrency. Uses a single conditional UPDATE so two concurrent claims on the
last unit cannot both succeed.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context


class InsufficientStock(Exception):
    pass


def use_inventory_part_atomic(
    db: Session, company_id: uuid.UUID, item_id: uuid.UUID, quantity: int
) -> int:
    """Deduct `quantity` of `item_id` atomically. Returns the new on-hand count.

    Raises ValueError if quantity <= 0. Raises InsufficientStock if there is
    not enough stock (or the item is not found in this tenant).
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    with tenant_context(db, company_id):
        result = db.execute(
            text(
                """
                UPDATE inventory_items
                   SET quantity_on_hand = quantity_on_hand - :qty,
                       low_stock_alerted = (quantity_on_hand - :qty < reorder_point)
                 WHERE id = :id
                   AND company_id::text = current_setting('app.current_company_id')
                   AND quantity_on_hand >= :qty
                RETURNING id, quantity_on_hand
                """
            ),
            {"id": item_id, "qty": quantity},
        )
        row = result.first()

    if row is None:
        raise InsufficientStock(
            f"insufficient stock for item {item_id} (requested {quantity})"
        )
    db.commit()
    return int(row.quantity_on_hand)
