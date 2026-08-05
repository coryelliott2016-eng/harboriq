"""Explicit state machines — illegal transitions raise before any write.

Every status change must load the actual current status under a row lock
(`SELECT status ... FOR UPDATE`) and then call assert_transition().
"""
from __future__ import annotations


class IllegalTransition(Exception):
    """Raised when a status transition is not allowed."""


class StateMachine:
    transitions: dict[str, set[str]] = {}

    @classmethod
    def assert_transition(cls, current: str, target: str) -> None:
        allowed = cls.transitions.get(current, set())
        if target not in allowed:
            raise IllegalTransition(
                f"Illegal transition: {current!r} -> {target!r}. "
                f"Allowed from {current!r}: {sorted(allowed) or 'none (terminal)'}"
            )

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        return target in cls.transitions.get(current, set())


class EstimateSM(StateMachine):
    transitions = {
        "draft": {"sent"},
        "sent": {"viewed", "approved", "declined", "expired"},
        "viewed": {"approved", "declined", "expired"},
        "approved": {"invoiced"},
        "declined": set(),
        "expired": set(),
        "invoiced": set(),
    }


class InvoiceSM(StateMachine):
    transitions = {
        # A draft that is never sent still needs a way to be cancelled — e.g.
        # the shop mis-scoped the job and wants to redo the line items rather
        # than mail a bill first and void it after. Phase 3 adds this edge
        # (previously `draft` had no exit besides `sent`) rather than forcing
        # a pointless send->void round-trip for work that never left the shop.
        "draft": {"sent", "void"},
        "sent": {"partial", "paid", "void", "uncollectible"},
        # Phase 8: a customer can have paid a deposit ("partial") and then
        # want that deposit refunded before ever paying the rest -- e.g. the
        # job gets cancelled after a deposit was taken. `partially_refunded`
        # is the right landing state either way (some money was paid, some
        # of what was paid has now been returned); `amount_paid` vs. the
        # refunded total is what distinguishes "still owes a balance" from
        # "fully settled the refunded portion", not the status enum alone.
        "partial": {"paid", "void", "partially_refunded"},
        "paid": {"refunded", "partially_refunded"},
        "void": set(),
        "uncollectible": set(),
        "refunded": set(),
        # A partial refund can be topped up by another partial refund (still
        # `partially_refunded`) or completed by refunding the remainder
        # (`refunded`) -- both computed by `refund_invoice` from amount_paid
        # vs. the newly-refunded total, not a fixed transition target.
        "partially_refunded": {"refunded", "partially_refunded"},
    }


class JobSM(StateMachine):
    transitions = {
        "scheduled": {"in_progress", "canceled"},
        "in_progress": {"on_hold", "completed", "canceled"},
        "on_hold": {"in_progress", "canceled"},
        "completed": set(),
        "canceled": set(),
    }


class SubscriptionSM(StateMachine):
    transitions = {
        "trialing": {"active", "canceled"},
        "active": {"past_due", "paused", "canceled"},
        "past_due": {"active", "canceled"},
        "paused": {"active", "canceled"},
        "canceled": set(),
    }


class PaymentSM(StateMachine):
    transitions = {
        "pending": {"succeeded", "failed"},
        "succeeded": {"refunded", "partially_refunded"},
        "failed": set(),
        "refunded": set(),
        "partially_refunded": set(),
    }


class PurchaseOrderSM(StateMachine):
    """Phase 13: draft -> submitted -> received, matching the
    Job/Invoice discipline of loading the row FOR UPDATE before asserting.

    Cancellation is allowed from `draft` or `submitted` -- a shop can back out
    of an order before the vendor ships or even after submitting but before
    anything arrives. It is NOT allowed from `received`: stock has already
    been incremented onto the shelf by then (real inventory movement, not
    just a paperwork state), so undoing it would need an explicit reversing
    adjustment, not a status flip. `received` and `cancelled` are both
    terminal, same as `refunded`/`void` elsewhere.
    """

    transitions = {
        "draft": {"submitted", "cancelled"},
        "submitted": {"received", "cancelled"},
        "received": set(),
        "cancelled": set(),
    }
