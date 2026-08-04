"""Customer <-> staff messaging: send/receive both directions, threading by
job, outbox notification, and tenant/customer isolation specifically on
messages.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.services.portal import issue_portal_token
from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def test_customer_can_send_and_read_own_messages(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    resp = client.post(f"/api/v1/portal/{token}/messages", json={"body": "When is my boat ready?"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sender_type"] == "customer"
    assert resp.json()["customer_id"] == customer_id

    listed = client.get(f"/api/v1/portal/{token}/messages").json()
    assert len(listed) == 1
    assert listed[0]["body"] == "When is my boat ready?"


def test_customer_message_notifies_office_staff_via_outbox(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    client.post(f"/api/v1/portal/{token}/messages", json={"body": "Any update?"})

    row = service_db.execute(
        text(
            "SELECT event_type, payload FROM outbox_events WHERE event_type = 'message.new_from_customer'"
        )
    ).first()
    assert row is not None
    assert row.payload["customer_id"] == customer_id
    assert row.payload["body"] == "Any update?"
    assert row.payload["to"] == owner["user"]["email"]


def test_staff_can_see_and_reply_to_customer_message(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    client.post(f"/api/v1/portal/{token}/messages", json={"body": "When is my boat ready?"})

    inbox = client.get("/api/v1/messages", headers=auth_headers(owner)).json()
    assert len(inbox) == 1
    assert inbox[0]["body"] == "When is my boat ready?"
    assert inbox[0]["sender_type"] == "customer"

    reply = client.post(
        "/api/v1/messages",
        json={"customer_id": customer_id, "body": "Ready Friday!"},
        headers=auth_headers(owner),
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["sender_type"] == "staff"
    assert reply.json()["sender_user_id"] == owner["user"]["id"]

    thread = client.get(f"/api/v1/portal/{token}/messages").json()
    assert [m["body"] for m in thread] == ["When is my boat ready?", "Ready Friday!"]


def test_staff_reply_notifies_the_customer_via_outbox(client, service_db):
    owner = signup(client)
    # A customer with an email on file -- the outbox notification is
    # best-effort and only queued when there is somewhere to send it.
    resp = client.post(
        "/api/v1/customers",
        json={"last_name": "Halyard", "email": "halyard@example.com"},
        headers=auth_headers(owner),
    )
    customer_id = resp.json()["id"]

    client.post(
        "/api/v1/messages",
        json={"customer_id": customer_id, "body": "Ready Friday!"},
        headers=auth_headers(owner),
    )

    row = service_db.execute(
        text(
            "SELECT event_type, payload FROM outbox_events WHERE event_type = 'message.new_from_staff'"
        )
    ).first()
    assert row is not None


def test_messages_thread_by_job(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    job = make_job(client, owner, customer_id).json()
    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    client.post(f"/api/v1/portal/{token}/messages", json={"body": "General question"})
    client.post(
        f"/api/v1/portal/{token}/messages",
        json={"body": "About this job", "job_id": job["id"]},
    )

    job_only = client.get(f"/api/v1/portal/{token}/messages?job_id={job['id']}").json()
    assert len(job_only) == 1
    assert job_only[0]["body"] == "About this job"

    staff_job_view = client.get(
        f"/api/v1/messages/by-job/{job['id']}", headers=auth_headers(owner)
    ).json()
    assert len(staff_job_view) == 1
    assert staff_job_view[0]["body"] == "About this job"


def test_technician_cannot_access_staff_messages_inbox(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get("/api/v1/messages", headers=auth_headers(tech))
    assert resp.status_code == 403


def test_customer_a_cannot_see_customer_bs_messages(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_a = make_customer(client, owner, last_name="Halyard")
    customer_b = make_customer(client, owner, last_name="Windward")

    token_a = issue_portal_token(service_db, company_id, uuid.UUID(customer_a))
    token_b = issue_portal_token(service_db, company_id, uuid.UUID(customer_b))

    client.post(f"/api/v1/portal/{token_a}/messages", json={"body": "A's secret question"})
    client.post(f"/api/v1/portal/{token_b}/messages", json={"body": "B's secret question"})

    thread_a = client.get(f"/api/v1/portal/{token_a}/messages").json()
    thread_b = client.get(f"/api/v1/portal/{token_b}/messages").json()

    assert [m["body"] for m in thread_a] == ["A's secret question"]
    assert [m["body"] for m in thread_b] == ["B's secret question"]


def test_tenant_isolation_across_companies_on_messages(client, service_db):
    owner_a = signup(client)
    company_a = uuid.UUID(owner_a["user"]["company_id"])
    customer_a = make_customer(client, owner_a)

    owner_b = signup(client)
    make_customer(client, owner_b)

    token_a = issue_portal_token(service_db, company_a, uuid.UUID(customer_a))
    client.post(f"/api/v1/portal/{token_a}/messages", json={"body": "Company A message"})

    # Company B staff must never see company A's message in their inbox.
    inbox_b = client.get("/api/v1/messages", headers=auth_headers(owner_b)).json()
    assert inbox_b == []


def test_staff_reply_to_unknown_customer_is_404(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/messages",
        json={"customer_id": str(uuid.uuid4()), "body": "hi"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


def test_message_body_cannot_be_blank(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    resp = client.post(f"/api/v1/portal/{token}/messages", json={"body": "   "})
    assert resp.status_code == 422
