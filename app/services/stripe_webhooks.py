"""Stripe webhook handling — idempotent + tenant-resolved + outbox for side effects.

Idempotency: INSERT ... ON CONFLICT (stripe_event_id) DO NOTHING inside the
same transaction as the DB side effect. A concurrent duplicate delivery blocks
on the unique constraint, then sees the committed row and no-ops.

Transactional boundary:
  * DB side effects (state transitions, payment rows) run in the transaction.
  * Non-DB side effects (receipts, SMS, outbound webhooks) go to the outbox
    table in the SAME transaction and are dispatched after commit.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services import invoices, outbox

ALREADY_PROCESSED = "duplicate"


def resolve_company_from_event(db: Session, payload: dict[str, Any]) -> uuid.UUID:
    """Look up the owning company from Stripe metadata or the subscription.

    Uses the SERVICE session (BYPASSRLS) so RLS does not block the lookup.
    Webhooks are unauthenticated platform endpoints — company_id is never
    taken from the request.
    """
    obj = payload.get("data", {}).get("object", {})

    # Option A: metadata we stamped on the checkout session at creation.
    meta = obj.get("metadata", {}) or {}
    if meta.get("company_id"):
        return uuid.UUID(meta["company_id"])

    # Option B: resolve via stripe_subscription_id -> subscriptions.company_id.
    sub_id = obj.get("subscription") or obj.get("id")
    if sub_id:
        row = db.execute(
            text(
                "SELECT company_id FROM subscriptions WHERE stripe_subscription_id = :s"
            ),
            {"s": sub_id},
        ).first()
        if row:
            return uuid.UUID(str(row[0]))

    raise ValueError("Cannot resolve company_id from Stripe event")


def handle_stripe_webhook(db: Session, event_id: str, event_type: str, payload: dict) -> int:
    """Idempotent webhook handler. Returns HTTP status code (200 always, so
    Stripe stops retrying once processed)."""
    company_id = resolve_company_from_event(db, payload)

    with tenant_context(db, company_id):
        # Check-and-insert in the same transaction as the side effect. A
        # concurrent duplicate blocks on the unique constraint.
        inserted = db.execute(
            text(
                """
                INSERT INTO stripe_processed_events
                    (stripe_event_id, event_type, company_id, resource_id,
                     http_status, outcome)
                VALUES (:eid, :etype, :cid, :rid, 200, 'applied')
                ON CONFLICT (stripe_event_id) DO NOTHING
                RETURNING stripe_event_id
                """
            ),
            {
                "eid": event_id,
                "etype": event_type,
                "cid": company_id,
                "rid": payload.get("data", {}).get("object", {}).get("id"),
            },
        )

        if inserted.first() is None:
            # Already processed — idempotent no-op.
            return 200

        _apply_side_effect(db, event_type, payload, company_id)
        db.commit()
        return 200


def _apply_side_effect(db: Session, event_type: str, payload: dict, company_id: uuid.UUID) -> None:
    """Apply the DB state change; queue non-DB side effects via the outbox.

    IMPORTANT — two unrelated "invoice" concepts collide in Stripe's event
    names here and must not be conflated:
      * Stripe Billing subscription invoices (`invoice.payment_succeeded`) —
        HarborIQ's OWN SaaS subscription charge to the shop. Handled by
        `_on_subscription_payment_succeeded`, still a TODO stub; nothing in
        Phase 3 implements platform subscription billing.
      * `checkout.session.completed` with `metadata.kind == "invoice_payment"`
        — a marine-shop CUSTOMER paying one of the shop's `invoices` rows via
        the Phase 3 pay link. Handled by `_on_invoice_payment_completed`.
    A `checkout.session.completed` event with no such metadata (or a
    `subscription` field) is the pre-existing subscription-checkout flow and
    still routes to `_on_subscription_checkout_completed`.
    """
    obj = payload.get("data", {}).get("object", {})

    if event_type == "invoice.payment_succeeded":
        _on_subscription_payment_succeeded(db, company_id, obj)
    elif event_type == "checkout.session.completed":
        meta = obj.get("metadata", {}) or {}
        if meta.get("kind") == "invoice_payment":
            _on_invoice_payment_completed(db, company_id, obj)
        else:
            _on_subscription_checkout_completed(db, company_id, obj)
    elif event_type == "payment_intent.succeeded":
        # Fallback path: some integrations (or a customer paying via a saved
        # payment method outside Checkout) surface the payment as a bare
        # PaymentIntent rather than a completed Checkout Session. Only handle
        # it here if it is tagged as ours; otherwise there is nothing to do.
        meta = obj.get("metadata", {}) or {}
        if meta.get("kind") == "invoice_payment":
            _on_invoice_payment_completed(db, company_id, obj)
    # ... other event types as needed


def _on_subscription_payment_succeeded(db: Session, company_id: uuid.UUID, obj: dict) -> None:
    """Stripe Billing subscription invoice paid — HarborIQ's OWN SaaS charge
    to the shop for using the platform. Distinct from a shop's customer
    invoices (`app.services.invoices`), which is what Phase 3 implements.

    Still a TODO stub: platform subscription billing (plans, seats, usage
    metering) is not implemented yet. Renamed from `_on_payment_succeeded` in
    Phase 3 purely to stop the name colliding, in a reader's head, with the
    unrelated marine-shop invoice payments this phase adds.
    """
    amount_paid_cents = obj.get("amount_paid") or obj.get("amount")
    payment_intent = obj.get("payment_intent")

    # TODO: resolve the local subscription by a stored Stripe id, e.g.:
    #   inv = db.execute(text("""
    #       UPDATE subscriptions SET status='active'
    #        WHERE stripe_subscription_id = :sid
    #          AND company_id::text = current_setting('app.current_company_id')
    #        RETURNING id"""), {"sid": ...}).first()

    # Non-DB side effect: queue a receipt — dispatched after commit by the
    # outbox worker (same transaction as the dedup INSERT above).
    outbox.enqueue(
        db,
        company_id,
        "receipt.send",
        {"payment_intent": payment_intent, "amount_cents": amount_paid_cents},
    )


def _on_subscription_checkout_completed(db: Session, company_id: uuid.UUID, obj: dict) -> None:
    """Platform subscription checkout completed (the shop subscribing to
    HarborIQ itself) — unrelated to a shop's customer paying an invoice."""
    sub_id = obj.get("subscription")
    if sub_id:
        db.execute(
            text(
                """
                UPDATE subscriptions
                   SET status = 'active',
                       stripe_subscription_id = COALESCE(:sid, stripe_subscription_id)
                 WHERE company_id::text = current_setting('app.current_company_id')
                 RETURNING id
                """
            ),
            {"sid": sub_id},
        )


def _on_invoice_payment_completed(db: Session, company_id: uuid.UUID, obj: dict) -> None:
    """A marine-shop customer finished paying one of the shop's `invoices`
    rows via the Phase 3 Stripe Checkout pay link.

    Delegates the actual row-locked state transition to
    `app.services.invoices.mark_paid_from_webhook`, which is also directly
    unit-tested — this function only adapts the raw Stripe payload shape.
    """
    amount_total_cents = obj.get("amount_total") or obj.get("amount") or 0
    invoices.mark_paid_from_webhook(
        db,
        company_id,
        stripe_checkout_session_id=obj.get("id") if obj.get("object") == "checkout.session" else None,
        stripe_payment_intent_id=obj.get("payment_intent") or (obj.get("id") if obj.get("object") == "payment_intent" else None),
        amount_paid_cents=amount_total_cents,
    )

    outbox.enqueue(
        db,
        company_id,
        "invoice.paid",
        {"invoice_metadata": (obj.get("metadata") or {}).get("invoice_id")},
    )
