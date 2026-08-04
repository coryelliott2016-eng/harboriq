"""`/portal/me`, `/portal/jobs`, `/portal/invoices`, `/portal/estimates`
return correctly scoped real data end-to-end, and never another customer's
rows even within the same company.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.portal import issue_portal_token
from app.services.public_tokens import approve_estimate_with_token
from tests.conftest import auth_headers, make_estimate, signup
from tests.test_crm_jobs import make_customer, make_job, make_vessel


def _seed_customer_with_data(client, owner, service_db, company_id, last_name):
    customer_id = make_customer(client, owner, last_name=last_name)
    vessel_id = make_vessel(client, owner, customer_id, name=f"{last_name}'s Boat")
    job = make_job(client, owner, customer_id, vessel_id=vessel_id).json()

    client.post(
        f"/api/v1/jobs/{job['id']}/line-items",
        json={"kind": "labor", "description": "Work", "quantity": "1.00", "unit_price": "150.00"},
        headers=auth_headers(owner),
    )
    invoice = client.post(
        "/api/v1/invoices", json={"job_id": job["id"]}, headers=auth_headers(owner)
    ).json()

    estimate_id = make_estimate(service_db, company_id, status="sent", total="250.00")
    service_db.execute(
        text("UPDATE estimates SET customer_id = :cid WHERE id = :id"),
        {"cid": customer_id, "id": estimate_id},
    )
    service_db.commit()

    return {
        "customer_id": customer_id,
        "vessel_id": vessel_id,
        "job_id": job["id"],
        "invoice_id": invoice["id"],
        "estimate_id": str(estimate_id),
    }


def test_portal_me_returns_profile_and_vessels(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")

    token = issue_portal_token(service_db, company_id, uuid.UUID(data["customer_id"]))
    resp = client.get(f"/api/v1/portal/{token}/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == data["customer_id"]
    assert len(body["vessels"]) == 1
    assert body["vessels"][0]["id"] == data["vessel_id"]


def test_portal_jobs_returns_the_customers_jobs(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")

    token = issue_portal_token(service_db, company_id, uuid.UUID(data["customer_id"]))
    resp = client.get(f"/api/v1/portal/{token}/jobs")
    assert resp.status_code == 200, resp.text
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == data["job_id"]
    # narrower than the internal job schema: no notes/pricing fields at all
    assert "notes" not in jobs[0]


def test_portal_invoices_returns_the_customers_invoices_with_balance(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")

    token = issue_portal_token(service_db, company_id, uuid.UUID(data["customer_id"]))
    resp = client.get(f"/api/v1/portal/{token}/invoices")
    assert resp.status_code == 200, resp.text
    invoices = resp.json()
    assert len(invoices) == 1
    assert invoices[0]["id"] == data["invoice_id"]
    assert "balance_due" in invoices[0]


def test_portal_estimates_returns_the_customers_estimates(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")

    token = issue_portal_token(service_db, company_id, uuid.UUID(data["customer_id"]))
    resp = client.get(f"/api/v1/portal/{token}/estimates")
    assert resp.status_code == 200, resp.text
    estimates = resp.json()
    assert len(estimates) == 1
    assert estimates[0]["id"] == data["estimate_id"]


def test_estimate_approve_token_reuses_existing_public_approval_flow(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")

    token = issue_portal_token(service_db, company_id, uuid.UUID(data["customer_id"]))
    resp = client.post(f"/api/v1/portal/{token}/estimates/{data['estimate_id']}/approve-token")
    assert resp.status_code == 200, resp.text
    approve_path = resp.json()["approve_path"]
    assert approve_path.startswith("/api/v1/public/estimate/")
    assert approve_path.endswith("/approve")

    # Exercise the SAME service function the public approval route calls --
    # matches `tests/test_public_tokens.py`'s convention of calling
    # `approve_estimate_with_token` directly (the HTTP route's `client.host`
    # is a non-IP literal under TestClient and is irrelevant to what this
    # test is proving: that the portal hands out a token this exact
    # function accepts, not a duplicate approval implementation).
    raw_approve_token = approve_path.split("/")[-2]
    result = approve_estimate_with_token(
        service_db, raw_approve_token, ip="203.0.113.7", user_agent="TestUA/1.0",
        estimate_pdf_version="1",
    )
    assert result["estimate_id"] == data["estimate_id"]

    row = service_db.execute(
        text("SELECT status FROM estimates WHERE id = :id"), {"id": data["estimate_id"]}
    ).first()
    assert row.status == "approved"


def test_portal_never_returns_a_different_customers_jobs_invoices_estimates(client, service_db):
    """The customer-isolation guarantee, exercised across every data
    endpoint at once: two customers in the SAME company, each with their own
    job/invoice/estimate, and A's token must show only A's rows."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data_a = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")
    data_b = _seed_customer_with_data(client, owner, service_db, company_id, "Windward")

    token_a = issue_portal_token(service_db, company_id, uuid.UUID(data_a["customer_id"]))

    jobs = client.get(f"/api/v1/portal/{token_a}/jobs").json()
    invoices = client.get(f"/api/v1/portal/{token_a}/invoices").json()
    estimates = client.get(f"/api/v1/portal/{token_a}/estimates").json()

    assert [j["id"] for j in jobs] == [data_a["job_id"]]
    assert [i["id"] for i in invoices] == [data_a["invoice_id"]]
    assert [e["id"] for e in estimates] == [data_a["estimate_id"]]

    assert data_b["job_id"] not in [j["id"] for j in jobs]
    assert data_b["invoice_id"] not in [i["id"] for i in invoices]
    assert data_b["estimate_id"] not in [e["id"] for e in estimates]


def test_estimate_approve_token_for_another_customers_estimate_is_404(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    data_a = _seed_customer_with_data(client, owner, service_db, company_id, "Halyard")
    data_b = _seed_customer_with_data(client, owner, service_db, company_id, "Windward")

    token_a = issue_portal_token(service_db, company_id, uuid.UUID(data_a["customer_id"]))
    resp = client.post(
        f"/api/v1/portal/{token_a}/estimates/{data_b['estimate_id']}/approve-token"
    )
    assert resp.status_code == 404
