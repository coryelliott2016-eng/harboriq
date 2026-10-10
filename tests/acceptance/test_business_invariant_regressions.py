"""Defect-oriented acceptance cases for protected tenant, payment, and pricing rules."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.services.stripe_webhooks import handle_stripe_webhook
from tests.conftest import auth_headers, signup
from tests.test_estimates import LINES, _create, _job
from tests.test_stripe_invoice_webhook import (
    _checkout_completed_event,
    _invoiced_job,
)


def test_invoice_from_another_tenant_is_not_disclosed(client):
    tenant_a = signup(client, company_name="Acceptance Tenant A")
    tenant_b = signup(client, company_name="Acceptance Tenant B")
    _job_id, invoice = _invoiced_job(client, tenant_a)

    response = client.get(
        f"/api/v1/invoices/{invoice['id']}",
        headers=auth_headers(tenant_b),
    )

    assert response.status_code == 404


def test_overpayment_webhook_cannot_increase_invoice_amount_paid(
    client, service_db
):
    owner = signup(client, company_name="Acceptance Payments")
    _job_id, invoice = _invoiced_job(client, owner, unit_price="100.00")
    company_id = uuid.UUID(owner["user"]["company_id"])
    session_id = f"cs_acceptance_{uuid.uuid4().hex}"
    service_db.execute(
        text("UPDATE invoices SET stripe_checkout_session_id = :sid WHERE id = :id"),
        {"sid": session_id, "id": invoice["id"]},
    )
    service_db.commit()

    event_id = f"evt_acceptance_{uuid.uuid4().hex}"
    event = _checkout_completed_event(
        event_id, company_id, invoice["id"], session_id, 12500
    )
    assert handle_stripe_webhook(service_db, event_id, event["type"], event) == 200

    row = service_db.execute(
        text("SELECT status, amount_paid, balance_due FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).first()
    assert row.status == "paid"
    assert row.amount_paid == Decimal("100.00")
    assert row.balance_due == Decimal("0.00")


def test_client_forged_estimate_totals_do_not_override_server_pricing(client):
    owner = signup(client, company_name="Acceptance Pricing")
    job_id, _customer_id = _job(client, owner)
    forged_lines = [{**line, "line_total": "0.01"} for line in LINES]

    response = _create(
        client,
        owner,
        job_id,
        lines=forged_lines,
        tax_rate="0.07",
        subtotal="0.01",
        tax_total="0.00",
        total="0.01",
    )

    assert response.status_code == 201, response.text
    estimate = response.json()
    assert estimate["subtotal"] == "380.00"
    assert estimate["tax_total"] == "3.50"
    assert estimate["total"] == "383.50"
