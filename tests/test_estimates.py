"""Staff estimates: create -> send -> customer approves in portal -> convert to invoice.

Covers the end-to-end commercial workflow plus its guard rails: money math
(fractional labor hours, a non-taxable diagnostic fee), RBAC (technicians
cannot price work), tenant isolation, state-machine enforcement, outbox email,
audit logging, and that conversion bills exactly the approved lines.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.public_tokens import approve_estimate_with_token
from app.services.portal import issue_portal_token
from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_job


def _customer(client, actor, email: str | None = "skipper@example.com") -> str:
    body = {"last_name": "Halyard"}
    if email:
        body["email"] = email
    resp = client.post("/api/v1/customers", json=body, headers=auth_headers(actor))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _job(client, actor, email: str | None = "skipper@example.com") -> tuple[str, str]:
    customer_id = _customer(client, actor, email)
    job = make_job(client, actor, customer_id)
    assert job.status_code == 201, job.text
    return job.json()["id"], customer_id


LINES = [
    {"kind": "fee", "description": "Diagnostic fee", "quantity": "1.00",
     "unit_price": "150.00", "taxable": False},
    {"kind": "labor", "description": "Replace raw-water impeller", "quantity": "1.50",
     "unit_price": "120.00", "taxable": False},
    {"kind": "part", "description": "Impeller kit", "quantity": "2.00",
     "unit_price": "25.00"},
]


def _create(client, actor, job_id, lines=None, **fields):
    body = {"job_id": job_id, "line_items": LINES if lines is None else lines, **fields}
    return client.post("/api/v1/estimates", json=body, headers=auth_headers(actor))


def _approve_via_portal(client, service_db, owner, customer_id, estimate_id):
    company_id = uuid.UUID(owner["user"]["company_id"])
    portal_token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    resp = client.post(f"/api/v1/portal/{portal_token}/estimates/{estimate_id}/approve-token")
    assert resp.status_code == 200, resp.text
    raw = resp.json()["approve_path"].split("/")[-2]
    approve_estimate_with_token(
        service_db, raw, ip="203.0.113.9", user_agent="TestUA/1.0", estimate_pdf_version="1"
    )


def test_create_computes_totals_with_fractional_labor_and_untaxed_fee(client):
    owner = signup(client)
    job_id, customer_id = _job(client, owner)

    resp = _create(client, owner, job_id, tax_rate="0.07")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # 150.00 + 1.5*120.00 + 2*25.00 = 380.00; only the part line is taxable:
    # 50.00 * 0.07 = 3.50 -> total 383.50.
    assert body["subtotal"] == "380.00"
    assert body["tax_total"] == "3.50"
    assert body["total"] == "383.50"
    assert body["status"] == "draft"
    assert body["customer_id"] == customer_id
    assert [li["kind"] for li in body["line_items"]] == ["fee", "labor", "part"]
    assert body["line_items"][1]["quantity"] == "1.50"
    assert body["line_items"][1]["line_total"] == "180.00"
    assert body["invoice_id"] is None


def test_validation_rejects_empty_lines_bad_kinds_and_stock_on_labor(client):
    owner = signup(client)
    job_id, _ = _job(client, owner)

    assert _create(client, owner, job_id, lines=[]).status_code == 422
    storage = [{"kind": "storage", "description": "Slip", "quantity": "1", "unit_price": "1"}]
    assert _create(client, owner, job_id, lines=storage).status_code == 422
    negative = [{"kind": "labor", "description": "x", "quantity": "-1", "unit_price": "1"}]
    assert _create(client, owner, job_id, lines=negative).status_code == 422
    stocked_labor = [{"kind": "labor", "description": "x", "quantity": "1", "unit_price": "1",
                      "inventory_item_id": str(uuid.uuid4())}]
    assert _create(client, owner, job_id, lines=stocked_labor).status_code == 422
    assert _create(client, owner, str(uuid.uuid4())).status_code == 404


def test_technicians_cannot_create_or_read_estimates(client):
    owner = signup(client)
    job_id, _ = _job(client, owner)
    tech = invite(client, owner, "technician")

    assert _create(client, tech, job_id).status_code == 403
    assert client.get("/api/v1/estimates", headers=auth_headers(tech)).status_code == 403


def test_office_role_can_create_estimates(client):
    owner = signup(client)
    job_id, _ = _job(client, owner)
    office = invite(client, owner, "office")
    assert _create(client, office, job_id).status_code == 201


def test_estimates_are_isolated_between_tenants(client):
    owner_a = signup(client, company_name="Alpha Marine")
    owner_b = signup(client, company_name="Bravo Marine")
    job_a, _ = _job(client, owner_a)
    estimate_id = _create(client, owner_a, job_a).json()["id"]

    assert client.get(
        f"/api/v1/estimates/{estimate_id}", headers=auth_headers(owner_b)
    ).status_code == 404
    assert client.get("/api/v1/estimates", headers=auth_headers(owner_b)).json() == []
    assert client.post(
        f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner_b)
    ).status_code == 404
    # Tenant B cannot attach an estimate to tenant A's job either.
    assert _create(client, owner_b, job_a).status_code == 404


def test_send_moves_to_sent_and_queues_a_portal_email(client, service_db):
    owner = signup(client)
    job_id, _ = _job(client, owner)
    estimate_id = _create(client, owner, job_id).json()["id"]

    resp = client.post(f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["estimate"]["status"] == "sent"
    assert resp.json()["estimate"]["sent_at"] is not None
    assert resp.json()["email_queued"] is True

    row = service_db.execute(
        text("SELECT payload FROM outbox_events WHERE event_type = 'estimate.send'")
    ).first()
    assert row is not None
    assert row.payload["customer_email"] == "skipper@example.com"
    assert "/portal/" in row.payload["portal_url"]
    assert row.payload["portal_url"].endswith("/estimates")

    # Sending twice is an illegal transition.
    again = client.post(f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner))
    assert again.status_code == 409


def test_send_without_customer_email_still_marks_sent(client):
    owner = signup(client)
    job_id, _ = _job(client, owner, email=None)
    estimate_id = _create(client, owner, job_id).json()["id"]
    resp = client.post(f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_queued"] is False


def test_convert_requires_customer_approval(client):
    owner = signup(client)
    job_id, _ = _job(client, owner)
    estimate_id = _create(client, owner, job_id).json()["id"]
    assert client.post(
        f"/api/v1/estimates/{estimate_id}/convert", headers=auth_headers(owner)
    ).status_code == 409
    client.post(f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner))
    assert client.post(
        f"/api/v1/estimates/{estimate_id}/convert", headers=auth_headers(owner)
    ).status_code == 409


def test_full_workflow_bills_exactly_the_approved_lines(client, service_db):
    owner = signup(client)
    job_id, customer_id = _job(client, owner)

    # An unrelated uninvoiced line already on the job must NOT be swept in.
    extra = client.post(
        f"/api/v1/jobs/{job_id}/line-items",
        json={"kind": "labor", "description": "Unrelated", "quantity": "1.00",
              "unit_price": "999.00"},
        headers=auth_headers(owner),
    )
    assert extra.status_code == 201, extra.text

    estimate_id = _create(client, owner, job_id, tax_rate="0.07").json()["id"]
    assert client.post(
        f"/api/v1/estimates/{estimate_id}/send", headers=auth_headers(owner)
    ).status_code == 200

    _approve_via_portal(client, service_db, owner, customer_id, estimate_id)
    approved = client.get(f"/api/v1/estimates/{estimate_id}", headers=auth_headers(owner)).json()
    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None

    conv = client.post(f"/api/v1/estimates/{estimate_id}/convert", headers=auth_headers(owner))
    assert conv.status_code == 200, conv.text
    assert conv.json()["estimate"]["status"] == "invoiced"
    invoice_id = conv.json()["invoice_id"]

    invoice = client.get(f"/api/v1/invoices/{invoice_id}", headers=auth_headers(owner)).json()
    assert invoice["estimate_id"] == estimate_id
    assert invoice["status"] == "draft"
    assert invoice["subtotal"] == "380.00"
    assert invoice["tax_total"] == "3.50"
    assert invoice["total"] == "383.50"
    assert sorted(li["description"] for li in invoice["line_items"]) == sorted(
        li["description"] for li in LINES
    )

    # The unrelated line is still uninvoiced and billable separately.
    job_lines = client.get(f"/api/v1/jobs/{job_id}/line-items", headers=auth_headers(owner)).json()
    unrelated = [li for li in job_lines if li["description"] == "Unrelated"]
    assert unrelated and unrelated[0]["invoice_id"] is None

    # Detail now links the invoice; converting twice is illegal.
    detail = client.get(f"/api/v1/estimates/{estimate_id}", headers=auth_headers(owner)).json()
    assert detail["invoice_id"] == invoice_id
    assert client.post(
        f"/api/v1/estimates/{estimate_id}/convert", headers=auth_headers(owner)
    ).status_code == 409

    # The converted invoice continues through the existing send lifecycle.
    sent = client.post(f"/api/v1/invoices/{invoice_id}/send", headers=auth_headers(owner))
    assert sent.status_code == 200, sent.text

    actions = [
        r.action for r in service_db.execute(
            text("SELECT action FROM audit_log WHERE resource_id = :id ORDER BY created_at"),
            {"id": estimate_id},
        ).all()
    ]
    assert actions == [
        "estimate.created", "estimate.sent", "estimate.approved", "estimate.invoiced",
    ]


def test_list_filters_by_job_and_status(client):
    owner = signup(client)
    job_a, _ = _job(client, owner)
    job_b, _ = _job(client, owner)
    first = _create(client, owner, job_a).json()["id"]
    _create(client, owner, job_b)
    client.post(f"/api/v1/estimates/{first}/send", headers=auth_headers(owner))

    by_job = client.get(f"/api/v1/estimates?job_id={job_a}", headers=auth_headers(owner)).json()
    assert [e["id"] for e in by_job] == [first]
    drafts = client.get("/api/v1/estimates?status=draft", headers=auth_headers(owner)).json()
    assert len(drafts) == 1 and drafts[0]["id"] != first
    bad = client.get("/api/v1/estimates?status=bogus", headers=auth_headers(owner))
    assert bad.status_code == 422
