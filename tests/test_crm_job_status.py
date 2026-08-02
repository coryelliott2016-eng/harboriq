"""Job status transitions — driven by `JobSM`, never written directly.

`test_state_machines.py` covers the transition table itself; these tests cover
the endpoint: that it consults the machine against the row's *actual* current
status, records the matching timestamps, and refuses illegal moves with a 409.
"""
from __future__ import annotations

import uuid

import pytest

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _set_status(client, actor, job_id, status, **fields):
    return client.post(
        f"/api/v1/jobs/{job_id}/status",
        json={"status": status, **fields},
        headers=auth_headers(actor),
    )


def _open_job(client, actor):
    return make_job(client, actor, make_customer(client, actor)).json()


def test_the_happy_path_through_the_shop(client):
    owner = signup(client)
    job = _open_job(client, owner)

    started = _set_status(client, owner, job["id"], "in_progress")
    assert started.status_code == 200, started.text
    assert started.json()["started_at"] is not None

    done = _set_status(client, owner, job["id"], "completed")
    assert done.status_code == 200
    assert done.json()["completed_at"] is not None


def test_a_hold_records_and_then_clears_its_reason(client):
    owner = signup(client)
    job = _open_job(client, owner)
    _set_status(client, owner, job["id"], "in_progress")

    held = _set_status(
        client, owner, job["id"], "on_hold", hold_reason="waiting on impeller"
    )
    assert held.status_code == 200, held.text
    assert held.json()["hold_reason"] == "waiting on impeller"

    resumed = _set_status(client, owner, job["id"], "in_progress")
    assert resumed.status_code == 200
    assert resumed.json()["hold_reason"] is None


def test_resuming_keeps_the_original_start_time(client):
    owner = signup(client)
    job = _open_job(client, owner)
    first = _set_status(client, owner, job["id"], "in_progress").json()
    _set_status(client, owner, job["id"], "on_hold")

    resumed = _set_status(client, owner, job["id"], "in_progress").json()
    assert resumed["started_at"] == first["started_at"]


@pytest.mark.parametrize("target", ["completed", "on_hold"])
def test_a_scheduled_job_cannot_skip_straight_to(client, target):
    owner = signup(client)
    job = _open_job(client, owner)

    resp = _set_status(client, owner, job["id"], target)
    assert resp.status_code == 409
    assert "Illegal transition" in resp.json()["detail"]


@pytest.mark.parametrize("target", ["scheduled", "in_progress", "canceled"])
def test_a_completed_job_is_terminal(client, target):
    owner = signup(client)
    job = _open_job(client, owner)
    _set_status(client, owner, job["id"], "in_progress")
    _set_status(client, owner, job["id"], "completed")

    resp = _set_status(client, owner, job["id"], target)
    assert resp.status_code == 409


def test_a_canceled_job_is_terminal(client):
    owner = signup(client)
    job = _open_job(client, owner)
    canceled = _set_status(client, owner, job["id"], "canceled")
    assert canceled.status_code == 200
    assert canceled.json()["canceled_at"] is not None

    assert _set_status(client, owner, job["id"], "in_progress").status_code == 409


def test_replaying_the_same_transition_is_refused(client):
    """The second request re-reads the row, so it is rejected rather than applied twice."""
    owner = signup(client)
    job = _open_job(client, owner)
    assert _set_status(client, owner, job["id"], "in_progress").status_code == 200
    assert _set_status(client, owner, job["id"], "in_progress").status_code == 409


def test_an_unknown_status_never_reaches_the_state_machine(client):
    owner = signup(client)
    job = _open_job(client, owner)
    assert _set_status(client, owner, job["id"], "invoiced").status_code == 422


def test_an_unknown_job_is_a_404(client):
    owner = signup(client)
    assert _set_status(client, owner, uuid.uuid4(), "in_progress").status_code == 404


# ---------------------------------------------------------------------------
# who may move a job
# ---------------------------------------------------------------------------
def test_the_assigned_technician_may_move_their_own_job(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _open_job(client, owner)
    client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    assert _set_status(client, tech, job["id"], "in_progress").status_code == 200


def test_a_technician_may_not_move_someone_elses_job(client):
    owner = signup(client)
    mine = invite(client, owner, "technician")
    theirs = invite(client, owner, "technician")
    job = _open_job(client, owner)
    client.post(
        f"/api/v1/jobs/{job['id']}/assign",
        json={"technician_id": theirs["user"]["id"]},
        headers=auth_headers(owner),
    )

    resp = _set_status(client, mine, job["id"], "in_progress")
    assert resp.status_code == 403


def test_a_technician_may_not_move_an_unassigned_job(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _open_job(client, owner)

    assert _set_status(client, tech, job["id"], "in_progress").status_code == 403


def test_office_staff_may_move_any_job(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    job = _open_job(client, owner)

    assert _set_status(client, office, job["id"], "in_progress").status_code == 200


def test_another_tenants_job_is_a_404_not_a_403(client):
    """A technician probing an id must not learn whether it exists elsewhere."""
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    tech = invite(client, b, "technician")
    job = _open_job(client, a)

    assert _set_status(client, tech, job["id"], "in_progress").status_code == 404
