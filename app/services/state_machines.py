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
        "draft": {"sent"},
        "sent": {"partial", "paid", "void", "uncollectible"},
        "partial": {"paid", "void"},
        "paid": {"refunded", "partially_refunded"},
        "void": set(),
        "uncollectible": set(),
        "refunded": set(),
        "partially_refunded": set(),
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
