"""Phase 11 dispatch board's assignment path.

The board has no assignment logic of its own — dragging a job onto a
technician column is a thin client-side wrapper around the exact same
`POST /jobs/{job_id}/assign` endpoint the Phase 7 ranked-candidate list
already uses (`app/api/v1/routes/jobs.py::assign_job`). These tests confirm
that endpoint (a) is the one and only assignment code path, (b) still
enqueues a job-confirmation SMS through the outbox on assignment, and (c)
that the ranked-score explanation used when assigning an unassigned job
(`GET /jobs/{id}/dispatch/candidates`) is untouched by this phase.
"""
from __future__ import annotations

from sqlalchemy import text

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _set_customer_phone(service_db, customer_id, phone):
    service_db.execute(
        text("UPDATE customers SET phone = :phone WHERE id = :id"),
        {"phone": phone, "id": customer_id},
    )
    service_db.commit()


def test_assign_endpoint_is_the_boards_assignment_mechanism(client, service_db):
    """Dragging a job onto a technician column calls this exact endpoint —
    confirm it actually assigns (the property both the ranked-list flow
    and the board depend on)."""
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["technician_id"] == tech["user"]["id"]


def test_assigning_enqueues_a_job_confirmation_sms_when_customer_has_a_phone(
    client, service_db
):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15551234567")
    job = make_job(client, owner, customer_id).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text(
            "SELECT event_type, payload FROM outbox_events "
            "WHERE event_type = 'sms.send' ORDER BY created_at DESC LIMIT 1"
        )
    ).first()
    assert row is not None
    assert row.payload["to"] == "+15551234567"
    assert job["title"] in row.payload["body"]


def test_assigning_does_not_enqueue_sms_when_customer_has_no_phone(
    client, service_db
):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text("SELECT id FROM outbox_events WHERE event_type = 'sms.send'")
    ).first()
    assert row is None


def test_unassigning_does_not_enqueue_a_confirmation_sms(client, service_db):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15551234567")
    job = make_job(client, owner, customer_id).json()

    client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )
    service_db.execute(text("DELETE FROM outbox_events"))
    service_db.commit()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": None},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["technician_id"] is None

    row = service_db.execute(
        text("SELECT id FROM outbox_events WHERE event_type = 'sms.send'")
    ).first()
    assert row is None


def test_ranked_dispatch_candidates_still_available_when_assigning_from_the_board(
    client,
):
    """The board upgrades, but does not replace, the Phase 7 ranked-list
    flow: `GET /jobs/{id}/dispatch/candidates` must still return a scored,
    explainable ranking the board's map/side-panel can show before the
    drag-and-drop assignment call fires."""
    owner = signup(client)
    invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.get(
        f"/api/v1/jobs/{job['id']}/dispatch/candidates", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    candidates = resp.json()
    assert len(candidates) >= 1
    assert "total" in candidates[0]["score"]
    assert "breakdown" in candidates[0]["score"]


def test_a_technician_cannot_assign_jobs(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403


def test_on_my_way_endpoint_enqueues_sms_for_the_assigned_technician(
    client, service_db
):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer_id = make_customer(client, owner)
    _set_customer_phone(service_db, customer_id, "+15551234567")
    job = make_job(client, owner, customer_id).json()

    client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )
    service_db.execute(text("DELETE FROM outbox_events"))
    service_db.commit()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/notify-on-my-way",
        headers=auth_headers(tech),
    )
    assert resp.status_code == 200, resp.text

    row = service_db.execute(
        text("SELECT payload FROM outbox_events WHERE event_type = 'sms.send'")
    ).first()
    assert row is not None
    assert row.payload["to"] == "+15551234567"
    assert "on the way" in row.payload["body"]


def test_on_my_way_forbidden_for_a_technician_not_assigned_to_the_job(client):
    owner = signup(client)
    invite(client, owner, "technician")
    other_tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/notify-on-my-way",
        headers=auth_headers(other_tech),
    )
    assert resp.status_code == 403


def test_on_my_way_is_a_noop_when_customer_has_no_phone(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    resp = client.post(
        f"/api/v1/jobs/{job['id']}/notify-on-my-way",
        headers=auth_headers(tech),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outbox_event_id"] is None
