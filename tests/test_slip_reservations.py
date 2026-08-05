"""Slip reservation lifecycle (state machine), availability, and tenant
isolation (Phase 15).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_vessel

TODAY = date(2026, 6, 1)


def _dates(offset_start=0, offset_end=3):
    return (
        (TODAY + timedelta(days=offset_start)).isoformat(),
        (TODAY + timedelta(days=offset_end)).isoformat(),
    )


def _slip(client, owner, **fields):
    body = {"identifier": "A-1", "slip_type": "wet_slip", **fields}
    resp = client.post("/api/v1/slips", json=body, headers=auth_headers(owner))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _reservation(client, owner, slip_id, customer_id, vessel_id=None, start=None, end=None):
    s, e = _dates() if start is None else (start, end)
    body = {
        "slip_id": slip_id, "customer_id": customer_id,
        "vessel_id": vessel_id, "start_date": s, "end_date": e,
    }
    return client.post("/api/v1/slip-reservations", json=body, headers=auth_headers(owner))


def test_create_reservation_defaults_to_pending(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    vessel_id = make_vessel(client, owner, customer_id)

    resp = _reservation(client, owner, slip_id, customer_id, vessel_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["checked_in_at"] is None


def test_end_date_before_start_date_rejected(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)

    s, e = _dates()
    resp = _reservation(client, owner, slip_id, customer_id, start=e, end=s)
    assert resp.status_code in (400, 409, 422), resp.text


def test_reservation_against_unknown_slip_is_404(client):
    owner = signup(client)
    customer_id = make_customer(client, owner)
    resp = _reservation(client, owner, str(uuid.uuid4()), customer_id)
    assert resp.status_code == 404


def test_overlapping_reservation_rejected_at_the_service_level(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)

    first = _reservation(client, owner, slip_id, customer_id)
    assert first.status_code == 201, first.text

    second = _reservation(client, owner, slip_id, customer_id)
    assert second.status_code == 409, second.text


def test_non_overlapping_reservation_on_same_slip_succeeds(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)

    s1, e1 = _dates(0, 3)
    s2, e2 = _dates(4, 7)
    first = _reservation(client, owner, slip_id, customer_id, start=s1, end=e1)
    second = _reservation(client, owner, slip_id, customer_id, start=s2, end=e2)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text


def test_full_lifecycle_confirm_check_in_check_out(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    reservation = _reservation(client, owner, slip_id, customer_id).json()
    rid = reservation["id"]

    confirmed = client.post(f"/api/v1/slip-reservations/{rid}/confirm", headers=auth_headers(owner))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    checked_in = client.post(f"/api/v1/slip-reservations/{rid}/check-in", headers=auth_headers(owner))
    assert checked_in.status_code == 200, checked_in.text
    assert checked_in.json()["status"] == "checked_in"
    assert checked_in.json()["checked_in_at"] is not None

    slip_after_checkin = client.get(f"/api/v1/slips/{slip_id}", headers=auth_headers(owner)).json()
    assert slip_after_checkin["status"] == "occupied"

    checked_out = client.post(f"/api/v1/slip-reservations/{rid}/check-out", headers=auth_headers(owner))
    assert checked_out.status_code == 200, checked_out.text
    assert checked_out.json()["status"] == "checked_out"

    slip_after_checkout = client.get(f"/api/v1/slips/{slip_id}", headers=auth_headers(owner)).json()
    assert slip_after_checkout["status"] == "available"


def test_cannot_check_in_a_reservation_that_is_still_pending(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id).json()["id"]

    resp = client.post(f"/api/v1/slip-reservations/{rid}/check-in", headers=auth_headers(owner))
    assert resp.status_code == 409, resp.text


def test_cannot_check_out_directly_from_confirmed(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id).json()["id"]
    client.post(f"/api/v1/slip-reservations/{rid}/confirm", headers=auth_headers(owner))

    resp = client.post(f"/api/v1/slip-reservations/{rid}/check-out", headers=auth_headers(owner))
    assert resp.status_code == 409, resp.text


def test_cancel_from_pending_frees_the_slip_for_rebooking(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id).json()["id"]

    cancelled = client.post(f"/api/v1/slip-reservations/{rid}/cancel", headers=auth_headers(owner))
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    rebooked = _reservation(client, owner, slip_id, customer_id)
    assert rebooked.status_code == 201, rebooked.text


def test_cannot_cancel_a_checked_out_reservation(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id).json()["id"]
    client.post(f"/api/v1/slip-reservations/{rid}/confirm", headers=auth_headers(owner))
    client.post(f"/api/v1/slip-reservations/{rid}/check-in", headers=auth_headers(owner))
    client.post(f"/api/v1/slip-reservations/{rid}/check-out", headers=auth_headers(owner))

    resp = client.post(f"/api/v1/slip-reservations/{rid}/cancel", headers=auth_headers(owner))
    assert resp.status_code == 409, resp.text


def test_availability_endpoint_reflects_existing_booking(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    s, e = _dates()
    _reservation(client, owner, slip_id, customer_id, start=s, end=e)

    resp = client.get(
        "/api/v1/slip-reservations/availability",
        params={"slip_id": slip_id, "start_date": s, "end_date": e},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["available"] is False

    free_s, free_e = _dates(30, 33)
    resp2 = client.get(
        "/api/v1/slip-reservations/availability",
        params={"slip_id": slip_id, "start_date": free_s, "end_date": free_e},
        headers=auth_headers(owner),
    )
    assert resp2.json()["available"] is True


def test_list_reservations_filters_by_status(client):
    owner = signup(client)
    slip_id = _slip(client, owner)
    customer_id = make_customer(client, owner)
    rid = _reservation(client, owner, slip_id, customer_id).json()["id"]
    client.post(f"/api/v1/slip-reservations/{rid}/confirm", headers=auth_headers(owner))

    resp = client.get(
        "/api/v1/slip-reservations", params={"status": "confirmed"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()] == [rid]


# ---------------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------------
def test_the_api_hides_another_tenants_reservation(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    slip_id = _slip(client, b)
    customer_id = make_customer(client, b)
    theirs = _reservation(client, b, slip_id, customer_id).json()

    resp = client.get(f"/api/v1/slip-reservations/{theirs['id']}", headers=auth_headers(a))
    assert resp.status_code == 404
    assert client.get("/api/v1/slip-reservations", headers=auth_headers(a)).json() == []


def test_the_api_refuses_to_transition_another_tenants_reservation(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    slip_id = _slip(client, b)
    customer_id = make_customer(client, b)
    theirs = _reservation(client, b, slip_id, customer_id).json()

    resp = client.post(
        f"/api/v1/slip-reservations/{theirs['id']}/confirm", headers=auth_headers(a)
    )
    assert resp.status_code == 404


def test_a_reservation_cannot_reference_another_tenants_slip(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    their_slip = _slip(client, b)
    customer_id = make_customer(client, a)

    resp = _reservation(client, a, their_slip, customer_id)
    assert resp.status_code == 404
