import pytest

from app.services.state_machines import (
    EstimateSM,
    IllegalTransition,
    InvoiceSM,
    JobSM,
    SubscriptionSM,
)


@pytest.mark.parametrize("current,target", [
    ("draft", "sent"),
    ("sent", "approved"),
    ("viewed", "approved"),
    ("approved", "invoiced"),
])
def test_estimate_legal_transitions(current, target):
    EstimateSM.assert_transition(current, target)


@pytest.mark.parametrize("current,target", [
    ("declined", "approved"),
    ("canceled", "paid"),
    ("approved", "draft"),
    ("expired", "approved"),
    ("draft", "approved"),   # must go through 'sent' first
])
def test_estimate_illegal_transitions(current, target):
    with pytest.raises(IllegalTransition):
        EstimateSM.assert_transition(current, target)


def test_invoice_paid_then_refunded():
    InvoiceSM.assert_transition("paid", "refunded")
    InvoiceSM.assert_transition("paid", "partially_refunded")
    with pytest.raises(IllegalTransition):
        InvoiceSM.assert_transition("void", "paid")


def test_job_terminal_states():
    with pytest.raises(IllegalTransition):
        JobSM.assert_transition("completed", "in_progress")
    with pytest.raises(IllegalTransition):
        JobSM.assert_transition("canceled", "in_progress")


def test_subscription_past_due_recovery():
    SubscriptionSM.assert_transition("past_due", "active")
    SubscriptionSM.assert_transition("active", "canceled")
    with pytest.raises(IllegalTransition):
        SubscriptionSM.assert_transition("canceled", "active")
