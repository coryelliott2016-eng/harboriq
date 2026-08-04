"""Portal magic-link issuance/resolution + the critical isolation guarantees.

Mirrors `tests/test_public_tokens.py`/`tests/test_public_invoice_pay.py`'s
conventions: issue tokens directly via the service layer, hit routes via
`client`, assert 404 (never 401) for anything not a live, correctly-scoped
token. The isolation tests are the point of this file: a portal token for
Customer A must never expose Customer B's data, even within the SAME
company.
"""
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text

from app.services.portal import issue_portal_token
from app.services.public_tokens import issue_public_token, revoke_public_token
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def test_issued_token_resolves_to_the_right_customer(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner, last_name="Halyard")
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    resp = client.get(f"/api/v1/portal/{token}/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == customer_id
    assert resp.json()["last_name"] == "Halyard"


def test_repeated_reads_do_not_consume_the_token(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))

    for _ in range(5):
        assert client.get(f"/api/v1/portal/{token}/me").status_code == 200

    row = service_db.execute(
        text("SELECT uses FROM public_tokens WHERE token_hash = :h"), {"h": _hash(token)}
    ).first()
    assert row.uses == 0


def test_wrong_purpose_is_a_404(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "customer", uuid.UUID(customer_id), "invoice_pay", ttl_hours=1
    )
    assert client.get(f"/api/v1/portal/{token}/me").status_code == 404


def test_wrong_resource_type_is_a_404(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_public_token(
        service_db, company_id, "estimate", uuid.UUID(customer_id), "portal", ttl_hours=1
    )
    assert client.get(f"/api/v1/portal/{token}/me").status_code == 404


def test_expired_token_is_a_404(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    service_db.execute(text("UPDATE public_tokens SET expires_at = now() - interval '1 hour'"))
    service_db.commit()

    assert client.get(f"/api/v1/portal/{token}/me").status_code == 404


def test_revoked_token_is_a_404(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    company_id = uuid.UUID(owner["user"]["company_id"])

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    revoke_public_token(service_db, _hash(token))

    assert client.get(f"/api/v1/portal/{token}/me").status_code == 404


def test_an_unknown_token_is_a_404(client):
    assert client.get("/api/v1/portal/not-a-real-token/me").status_code == 404


def test_customer_a_token_never_exposes_customer_b_data_same_company(client, service_db):
    """The critical isolation guarantee: RLS alone only separates tenants,
    not customers within one tenant, so this must be enforced in the
    application layer (see `app.services.portal` module docstring)."""
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_a = make_customer(client, owner, last_name="Halyard")
    customer_b = make_customer(client, owner, last_name="Windward")

    token_a = issue_portal_token(service_db, company_id, uuid.UUID(customer_a))

    resp = client.get(f"/api/v1/portal/{token_a}/me")
    assert resp.status_code == 200
    assert resp.json()["id"] == customer_a
    assert resp.json()["id"] != customer_b

    # Jobs/invoices/estimates lists for A's token must never contain B's rows
    # even if B has data — covered end-to-end in test_portal_data.py; here we
    # additionally confirm /me itself never leaks B under any circumstance.
    assert "Windward" not in resp.text


def test_portal_token_across_companies_is_tenant_isolated(client, service_db):
    """A token issued for a customer in company A must never resolve for
    company B's tenant context (belt-and-suspenders on top of the
    resource_id match: the token row itself carries company_id)."""
    owner_a = signup(client)
    company_a = uuid.UUID(owner_a["user"]["company_id"])
    customer_a = make_customer(client, owner_a, last_name="Halyard")

    owner_b = signup(client)
    company_b = uuid.UUID(owner_b["user"]["company_id"])
    customer_b = make_customer(client, owner_b, last_name="Windward")

    token_a = issue_portal_token(service_db, company_a, uuid.UUID(customer_a))
    token_b = issue_portal_token(service_db, company_b, uuid.UUID(customer_b))

    resp_a = client.get(f"/api/v1/portal/{token_a}/me")
    resp_b = client.get(f"/api/v1/portal/{token_b}/me")
    assert resp_a.json()["id"] == customer_a
    assert resp_b.json()["id"] == customer_b
    assert resp_a.json()["id"] != resp_b.json()["id"]


def test_staff_portal_invite_issues_a_working_token(client, service_db):
    owner = signup(client)
    customer_id = make_customer(client, owner)

    resp = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["customer_id"] == customer_id

    row = service_db.execute(
        text(
            "SELECT event_type, payload FROM outbox_events WHERE event_type = 'customer.portal_invite'"
        )
    ).first()
    assert row is not None
    assert row.payload["customer_id"] == customer_id
    assert "/portal/" in row.payload["portal_url"]


def test_portal_invite_requires_operations_role(client):
    owner = signup(client)
    customer_id = make_customer(client, owner)

    from tests.conftest import invite

    tech = invite(client, owner, "technician")
    resp = client.post(
        f"/api/v1/customers/{customer_id}/portal-invite", headers=auth_headers(tech)
    )
    assert resp.status_code == 403


def test_portal_invite_for_unknown_customer_is_404(client):
    owner = signup(client)
    resp = client.post(
        f"/api/v1/customers/{uuid.uuid4()}/portal-invite", headers=auth_headers(owner)
    )
    assert resp.status_code == 404
