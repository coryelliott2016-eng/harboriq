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
    """Look up the owning company from Stripe metadata, Connect's `account`
    context, or the subscription.

    Uses the SERVICE session (BYPASSRLS) so RLS does not block the lookup.
    Webhooks are unauthenticated platform endpoints — company_id is never
    taken from the request.
    """
    obj = payload.get("data", {}).get("object", {})

    # Option A: metadata we stamped on the checkout session at creation. Set
    # regardless of whether the session was created directly on the platform
    # account or (Phase 8+) directly on a tenant's connected account, so this
    # remains the primary resolution path either way.
    meta = obj.get("metadata", {}) or {}
    if meta.get("company_id"):
        return uuid.UUID(meta["company_id"])

    # Option B (Phase 8 — Connect): events for a direct charge created on a
    # connected account arrive with a top-level `account` field (the
    # connected account id) rather than under `data.object`. Metadata should
    # normally resolve first, but this covers events where it is absent
    # (e.g. some account-level events Stripe sends without our metadata).
    account_id = payload.get("account")
    if account_id:
        row = db.execute(
            text("SELECT id FROM companies WHERE stripe_connect_account_id = :a"),
            {"a": account_id},
        ).first()
        if row:
            return uuid.UUID(str(row[0]))

    # Option C: resolve via stripe_subscription_id -> subscriptions.company_id.
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

    # Option D (Phase 17, Area E): a `charge.refunded` event's charge object
    # normally carries an EMPTY `metadata` -- Stripe does not automatically
    # copy Checkout Session metadata onto the Charge it produces -- so
    # Option A almost never resolves for this event type. Fall back to the
    # invoice this charge/payment_intent is already tied to (stamped by
    # `mark_paid_from_webhook` when the original payment was processed).
    payment_intent_id = obj.get("payment_intent") or (
        obj.get("id") if obj.get("object") == "payment_intent" else None
    )
    if payment_intent_id:
        row = db.execute(
            text("SELECT company_id FROM invoices WHERE stripe_payment_intent_id = :pi"),
            {"pi": payment_intent_id},
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

    `charge.refunded` (Phase 17, Area E) is a THIRD, independent path from
    the two "invoice" concepts above: it reconciles a refund that happened
    directly in Stripe (Dashboard or API) outside HarborIQ's own
    `POST /invoices/{id}/refund` flow -- see `_on_charge_refunded`.
    """
    obj = payload.get("data", {}).get("object", {})

    if event_type == "invoice.payment_succeeded":
        _on_subscription_payment_succeeded(db, company_id, obj)
    elif event_type == "checkout.session.completed":
        meta = obj.get("metadata", {}) or {}
        kind = meta.get("kind")
        if kind == "invoice_payment":
            _on_invoice_payment_completed(db, company_id, obj)
        elif kind == "crypto_invoice_payment":
            # Phase 18: stablecoin Checkout created by
            # app.services.crypto_payments.StripeStablecoinProvider. Real Stripe
            # events land on THIS endpoint (Stripe-Signature verification),
            # not on the generic HMAC /webhooks/crypto path — that path remains
            # for non-Stripe licensed processors and local tests.
            _on_crypto_invoice_payment_completed(db, company_id, obj)
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
        elif meta.get("kind") == "crypto_invoice_payment":
            _on_crypto_invoice_payment_completed(db, company_id, obj)
    elif event_type == "charge.refunded":
        _on_charge_refunded(db, company_id, obj)
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


def _on_crypto_invoice_payment_completed(
    db: Session, company_id: uuid.UUID, obj: dict
) -> None:
    """A marine-shop customer finished a Phase 18 stablecoin Checkout Session.

    Mirrors `_on_invoice_payment_completed` for money application, then
    advances the matching `crypto_payments` row from `pending` -> `confirmed`
    so ops can see which rail collected the funds. The invoice is resolved by
    the Checkout Session id stamped onto `invoices.stripe_checkout_session_id`
    at intent-creation time (see `create_crypto_payment_intent`).
    """
    import json

    session_id = obj.get("id") if obj.get("object") == "checkout.session" else None
    payment_intent_id = obj.get("payment_intent") or (
        obj.get("id") if obj.get("object") == "payment_intent" else None
    )
    amount_total_cents = obj.get("amount_total") or obj.get("amount") or 0
    meta = obj.get("metadata") or {}

    if session_id:
        # Idempotent on status: a replay is already stopped by
        # stripe_processed_events; this UPDATE is a no-op if already confirmed.
        db.execute(
            text(
                """
                UPDATE crypto_payments
                   SET status = 'confirmed',
                       confirmed_at = COALESCE(confirmed_at, now()),
                       raw_metadata = COALESCE(raw_metadata, '{}'::jsonb)
                           || jsonb_build_object(
                                  'stripe_event_object', CAST(:obj AS jsonb),
                                  'confirmed_via', 'stripe_webhook'
                              )
                 WHERE company_id = :company_id
                   AND provider = 'stripe_stablecoin'
                   AND provider_reference = :session_id
                   AND status = 'pending'
                """
            ),
            {
                "company_id": company_id,
                "session_id": session_id,
                "obj": json.dumps(obj, default=str),
            },
        )

    invoices.mark_paid_from_webhook(
        db,
        company_id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=payment_intent_id,
        amount_paid_cents=amount_total_cents,
    )

    crypto_payment_id = None
    if session_id:
        row = db.execute(
            text(
                """
                SELECT id FROM crypto_payments
                 WHERE company_id = :company_id
                   AND provider_reference = :session_id
                """
            ),
            {"company_id": company_id, "session_id": session_id},
        ).first()
        if row is not None:
            crypto_payment_id = str(row.id)

    outbox.enqueue(
        db,
        company_id,
        "invoice.paid",
        {
            "invoice_id": meta.get("invoice_id"),
            "crypto_payment_id": crypto_payment_id,
            "provider": "stripe_stablecoin",
            "confirmed_via": "stripe_webhook",
        },
    )


def _on_charge_refunded(db: Session, company_id: uuid.UUID, obj: dict) -> None:
    """A `charge` object's refund state changed (Phase 17, Area E) -- most
    commonly because staff issued a full or partial refund directly in the
    Stripe Dashboard, entirely outside HarborIQ's own
    `POST /invoices/{id}/refund` flow. Reconciles the local `invoices`/
    `refunds` tables so the books stay correct regardless of where the
    refund was initiated.

    A `charge.refunded` event's `refunds` field is a list object
    (`obj["refunds"]["data"]`), not a single refund -- Stripe re-fires this
    same event type with a growing list every time ANOTHER refund is issued
    against the same charge, so this walks the whole list and lets
    `invoices.reconcile_refund_from_webhook`'s per-`stripe_refund_id`
    idempotency check (backed by migration 0018's unique index) skip
    whichever ones were already applied on a prior delivery.
    """
    payment_intent_id = obj.get("payment_intent")
    charge_id = obj.get("id") if obj.get("object") == "charge" else None
    refund_list = (obj.get("refunds") or {}).get("data") or []

    for refund_obj in refund_list:
        # Only a `succeeded` refund actually moved money; `pending`/`failed`
        # entries in the same list must not touch the local ledger.
        if refund_obj.get("status") not in (None, "succeeded"):
            continue
        refund_id = refund_obj.get("id")
        if not refund_id:
            continue
        invoices.reconcile_refund_from_webhook(
            db,
            company_id,
            stripe_refund_id=refund_id,
            stripe_payment_intent_id=payment_intent_id,
            stripe_charge_id=charge_id,
            amount_refunded_cents=refund_obj.get("amount") or 0,
            reason=refund_obj.get("reason"),
        )
