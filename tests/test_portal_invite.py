"""Staff-triggered portal invite generation + delivery via the outbox.

Mirrors `tests/test_invoices.py`'s `send`-flow conventions: issuing an
action queues an outbox row with everything a customer needs, rather than
this test asserting an email was literally transmitted (dispatch itself is
covered by `tests/test_outbox*.py`).
"""
from __future__ import annotations


from sqlalchemy import text

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer


def test_portal_invite_issues_a_token_and_queues_an_email(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)

    resp = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["customer_id"] == customer_id
    assert isinstance(body["outbox_event_id"], int)

    token_row = service_db.execute(
        text("SELECT purpose, resource_type, resource_id FROM public_tokens WHERE resource_id = :cid"),
        {"cid": customer_id},
    ).first()
    assert token_row.purpose == "portal"
    assert token_row.resource_type == "customer"

    outbox_row = service_db.execute(
        text("SELECT event_type, payload FROM outbox_events WHERE id = :id"),
        {"id": body["outbox_event_id"]},
    ).first()
    assert outbox_row.event_type == "customer.portal_invite"
    assert outbox_row.payload["customer_id"] == customer_id
    assert "/portal/" in outbox_row.payload["portal_url"]


def test_portal_invite_can_be_resent_to_renew_the_link(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)

    first = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(owner)
    ).json()
    second = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(owner)
    ).json()
    assert first["outbox_event_id"] != second["outbox_event_id"]

    count = service_db.execute(
        text("SELECT count(*) AS n FROM public_tokens WHERE resource_id = :cid AND purpose = 'portal'"),
        {"cid": customer_id},
    ).first()
    assert count.n == 2


def test_only_operations_roles_may_send_a_portal_invite(client):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    tech = invite(client, owner, "technician")

    resp = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(tech)
    )
    assert resp.status_code == 403


def test_portal_invite_for_a_customer_in_another_tenant_is_404(client):
    owner_a = signup(client)
    owner_b = signup(client)
    customer_b = make_customer(client, owner_b)

    resp = client.post(
        f"/api/v1/customers/{customer_b}/portal-invite", headers=auth_headers(owner_a)
    )
    assert resp.status_code == 404
