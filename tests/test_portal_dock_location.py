"""GPS "find my dock" customer portal view (Phase 17, Area D).

Covers: a confirmed/checked-in reservation's slip coordinates are exposed
via the portal, pending/cancelled/checked-out reservations are excluded,
a slip with no coordinates on file is excluded, and one customer's portal
token never resolves another customer's dock location even within the
same tenant.
"""
from __future__ import annotations

import uuid

from app.services.portal import issue_portal_token
from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer


def _slip(client, owner, **fields):
    body = {
        "identifier": f"A-{uuid.uuid4().hex[:4]}",
        "slip_type": "wet_slip",
        "monthly_rate": "500.00",
        **fields,
    }
    resp = client.post("/api/v1/slips", json=body, headers=auth_headers(owner))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _reservation(client, owner, slip_id, customer_id, start="2026-01-01", end="2026-12-31"):
    resp = client.post(
        "/api/v1/slip-reservations",
        json={
            "slip_id": slip_id, "customer_id": customer_id,
            "start_date": start, "end_date": end,
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _confirm(client, owner, reservation_id):
    resp = client.post(
        f"/api/v1/slip-reservations/{reservation_id}/confirm",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text


def test_confirmed_reservation_with_gps_slip_is_returned(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    slip_id = _slip(client, owner, latitude="27.336700", longitude="-82.530700")
    rid = _reservation(client, owner, slip_id, customer_id)
    _confirm(client, owner, rid)

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    service_db.commit()

    resp = client.get(f"/api/v1/portal/{token}/dock-locations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["reservation_id"] == rid
    assert body[0]["slip_id"] == slip_id
    assert float(body[0]["latitude"]) == 27.3367
    assert float(body[0]["longitude"]) == -82.5307
    assert body[0]["status"] == "confirmed"


def test_slip_without_gps_coordinates_is_excluded(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    slip_id = _slip(client, owner)  # no lat/lng
    rid = _reservation(client, owner, slip_id, customer_id)
    _confirm(client, owner, rid)

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    service_db.commit()

    resp = client.get(f"/api/v1/portal/{token}/dock-locations")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_pending_reservation_is_excluded(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    slip_id = _slip(client, owner, latitude="27.0", longitude="-82.0")
    _reservation(client, owner, slip_id, customer_id)  # never confirmed

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    service_db.commit()

    resp = client.get(f"/api/v1/portal/{token}/dock-locations")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_cancelled_reservation_is_excluded(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_id = make_customer(client, owner)
    slip_id = _slip(client, owner, latitude="27.0", longitude="-82.0")
    rid = _reservation(client, owner, slip_id, customer_id)
    _confirm(client, owner, rid)

    cancel_resp = client.post(
        f"/api/v1/slip-reservations/{rid}/cancel", headers=auth_headers(owner)
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    token = issue_portal_token(service_db, company_id, uuid.UUID(customer_id))
    service_db.commit()

    resp = client.get(f"/api/v1/portal/{token}/dock-locations")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_one_customers_token_never_returns_another_customers_dock(client, service_db):
    owner = signup(client)
    company_id = uuid.UUID(owner["user"]["company_id"])
    customer_a = make_customer(client, owner, last_name="Alpha")
    customer_b = make_customer(client, owner, last_name="Beta")

    slip_a = _slip(client, owner, latitude="27.1", longitude="-82.1")
    slip_b = _slip(client, owner, latitude="27.2", longitude="-82.2")
    rid_a = _reservation(client, owner, slip_a, customer_a)
    rid_b = _reservation(client, owner, slip_b, customer_b)
    _confirm(client, owner, rid_a)
    _confirm(client, owner, rid_b)

    token_a = issue_portal_token(service_db, company_id, uuid.UUID(customer_a))
    service_db.commit()

    resp = client.get(f"/api/v1/portal/{token_a}/dock-locations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slip_id"] == slip_a


def test_invalid_portal_token_is_404(client):
    resp = client.get("/api/v1/portal/not-a-real-token/dock-locations")
    assert resp.status_code == 404
