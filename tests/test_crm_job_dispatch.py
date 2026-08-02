"""Dispatch (assignment) and the scheduling board feed."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _assign(client, actor, job_id, technician_id):
    return client.post(
        f"/api/v1/jobs/{job_id}/assign",
        json={"technician_id": technician_id},
        headers=auth_headers(actor),
    )


def _at(day: int, hour: int = 9) -> str:
    return datetime(2026, 5, day, hour, tzinfo=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# assignment
# ---------------------------------------------------------------------------
def test_assign_and_unassign(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    assigned = _assign(client, owner, job["id"], tech["user"]["id"])
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["technician_id"] == tech["user"]["id"]

    cleared = _assign(client, owner, job["id"], None)
    assert cleared.status_code == 200
    assert cleared.json()["technician_id"] is None


def test_a_job_can_be_assigned_at_creation(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = make_job(
        client,
        owner,
        make_customer(client, owner),
        technician_id=tech["user"]["id"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["technician_id"] == tech["user"]["id"]


def test_office_staff_cannot_be_dispatched_a_job(client):
    """A work order goes to somebody who turns wrenches."""
    owner = signup(client)
    office = invite(client, owner, "office")
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = _assign(client, owner, job["id"], office["user"]["id"])
    assert resp.status_code == 422
    assert "cannot be assigned" in resp.json()["detail"]


def test_an_owner_may_be_dispatched_a_job(client):
    """In a small yard the owner turns the wrenches too."""
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()
    assert _assign(client, owner, job["id"], owner["user"]["id"]).status_code == 200


def test_a_deactivated_user_cannot_be_dispatched_a_job(client, service_db):
    from sqlalchemy import text

    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = make_job(client, owner, make_customer(client, owner)).json()

    service_db.execute(
        text("UPDATE users SET is_active = false WHERE id = :uid"),
        {"uid": tech["user"]["id"]},
    )
    service_db.commit()

    resp = _assign(client, owner, job["id"], tech["user"]["id"])
    assert resp.status_code == 422
    assert "not active" in resp.json()["detail"]


def test_a_technician_from_another_tenant_cannot_be_dispatched(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    outsider = invite(client, b, "technician")
    job = make_job(client, a, make_customer(client, a)).json()

    assert _assign(client, a, job["id"], outsider["user"]["id"]).status_code == 422


def test_an_unknown_user_cannot_be_dispatched(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()
    assert _assign(client, owner, job["id"], str(uuid.uuid4())).status_code == 422


def test_only_operations_roles_may_create_or_dispatch(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer = make_customer(client, owner)
    job = make_job(client, owner, customer).json()

    assert make_job(client, tech, customer).status_code == 403
    assert _assign(client, tech, job["id"], tech["user"]["id"]).status_code == 403
    assert client.patch(
        f"/api/v1/jobs/{job['id']}", json={"title": "Nope"}, headers=auth_headers(tech)
    ).status_code == 403
    assert client.delete(
        f"/api/v1/jobs/{job['id']}", headers=auth_headers(tech)
    ).status_code == 403


def test_office_staff_may_create_and_dispatch(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    tech = invite(client, owner, "technician")
    customer = make_customer(client, owner)

    job = make_job(client, office, customer)
    assert job.status_code == 201, job.text
    assert _assign(
        client, office, job.json()["id"], tech["user"]["id"]
    ).status_code == 200


# ---------------------------------------------------------------------------
# the board
# ---------------------------------------------------------------------------
def test_the_schedule_is_a_half_open_window_ordered_by_time(client):
    owner = signup(client)
    customer = make_customer(client, owner)
    for day, title in ((1, "Mon"), (2, "Tue"), (3, "Wed")):
        make_job(client, owner, customer, title=title, scheduled_at=_at(day))

    resp = client.get(
        "/api/v1/jobs/schedule",
        params={"start": _at(1), "end": _at(3)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    # `start` is inclusive, `end` exclusive, so Wed (exactly at `end`) is out.
    assert [job["title"] for job in resp.json()] == ["Mon", "Tue"]


def test_the_schedule_omits_unscheduled_jobs(client):
    owner = signup(client)
    customer = make_customer(client, owner)
    make_job(client, owner, customer, title="Someday")
    make_job(client, owner, customer, title="Booked", scheduled_at=_at(1))

    board = client.get("/api/v1/jobs/schedule", headers=auth_headers(owner)).json()
    assert [job["title"] for job in board] == ["Booked"]


def test_the_schedule_can_be_filtered_to_one_technician(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    customer = make_customer(client, owner)
    mine = make_job(
        client, owner, customer, title="Mine", scheduled_at=_at(1)
    ).json()
    make_job(client, owner, customer, title="Theirs", scheduled_at=_at(2))
    _assign(client, owner, mine["id"], tech["user"]["id"])

    board = client.get(
        "/api/v1/jobs/schedule",
        params={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    ).json()
    assert [job["title"] for job in board] == ["Mine"]


def test_the_schedule_can_be_filtered_by_status(client):
    owner = signup(client)
    customer = make_customer(client, owner)
    cancelled = make_job(
        client, owner, customer, title="Dropped", scheduled_at=_at(1)
    ).json()
    make_job(client, owner, customer, title="Live", scheduled_at=_at(2))
    client.post(
        f"/api/v1/jobs/{cancelled['id']}/status",
        json={"status": "canceled"},
        headers=auth_headers(owner),
    )

    board = client.get(
        "/api/v1/jobs/schedule",
        params={"status": "scheduled"},
        headers=auth_headers(owner),
    ).json()
    assert [job["title"] for job in board] == ["Live"]


def test_a_backwards_window_is_rejected(client):
    owner = signup(client)
    resp = client.get(
        "/api/v1/jobs/schedule",
        params={"start": _at(3), "end": _at(1)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_a_technician_can_read_their_board(client):
    """Reading the schedule is not an operations action."""
    owner = signup(client)
    tech = invite(client, owner, "technician")
    assert client.get(
        "/api/v1/jobs/schedule", headers=auth_headers(tech)
    ).status_code == 200


def test_the_schedule_requires_authentication(client):
    assert client.get("/api/v1/jobs/schedule").status_code == 401
