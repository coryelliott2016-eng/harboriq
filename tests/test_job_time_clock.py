"""Job time clock (clock-in/out) — Phase 12 field app."""
from __future__ import annotations

import uuid

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _clock_in(client, actor, job_id, **fields):
    return client.post(
        f"/api/v1/jobs/{job_id}/clock-in", json=fields, headers=auth_headers(actor)
    )


def _clock_out(client, actor, job_id, **fields):
    return client.post(
        f"/api/v1/jobs/{job_id}/clock-out", json=fields, headers=auth_headers(actor)
    )


def test_owner_can_clock_in_and_out(client):
    owner = signup(client)
    job = _job(client, owner)

    in_resp = _clock_in(client, owner, job)
    assert in_resp.status_code == 201, in_resp.text
    entry = in_resp.json()
    assert entry["job_id"] == job
    assert entry["clocked_in_at"] is not None
    assert entry["clocked_out_at"] is None

    out_resp = _clock_out(client, owner, job)
    assert out_resp.status_code == 200, out_resp.text
    assert out_resp.json()["id"] == entry["id"]
    assert out_resp.json()["clocked_out_at"] is not None


def test_cannot_clock_in_twice_without_clocking_out(client):
    owner = signup(client)
    job = _job(client, owner)

    assert _clock_in(client, owner, job).status_code == 201
    second = _clock_in(client, owner, job)
    assert second.status_code == 409
    assert "already clocked in" in second.json()["detail"]


def test_cannot_clock_out_without_clocking_in(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _clock_out(client, owner, job)
    assert resp.status_code == 422
    assert "not clocked in" in resp.json()["detail"]


def test_can_clock_in_again_after_clocking_out(client):
    owner = signup(client)
    job = _job(client, owner)

    first_in = _clock_in(client, owner, job).json()
    _clock_out(client, owner, job)
    second_in = _clock_in(client, owner, job)
    assert second_in.status_code == 201
    assert second_in.json()["id"] != first_in["id"]


def test_time_entries_list_in_clock_in_order(client):
    owner = signup(client)
    job = _job(client, owner)
    _clock_in(client, owner, job)
    _clock_out(client, owner, job)
    _clock_in(client, owner, job)

    entries = client.get(
        f"/api/v1/jobs/{job}/time-entries", headers=auth_headers(owner)
    ).json()
    assert len(entries) == 2
    assert entries[0]["clocked_out_at"] is not None
    assert entries[1]["clocked_out_at"] is None


def test_idempotent_replay_of_clock_in_returns_the_same_entry(client):
    owner = signup(client)
    job = _job(client, owner)
    key = str(uuid.uuid4())

    first = _clock_in(client, owner, job, idempotency_key=key)
    assert first.status_code == 201
    second = _clock_in(client, owner, job, idempotency_key=key)
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    entries = client.get(
        f"/api/v1/jobs/{job}/time-entries", headers=auth_headers(owner)
    ).json()
    assert len(entries) == 1


def test_idempotent_replay_of_clock_out_returns_the_closed_entry(client):
    owner = signup(client)
    job = _job(client, owner)
    key = str(uuid.uuid4())

    _clock_in(client, owner, job)
    first = _clock_out(client, owner, job, idempotency_key=key)
    assert first.status_code == 200
    second = _clock_out(client, owner, job, idempotency_key=key)
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["clocked_out_at"] == second.json()["clocked_out_at"]


def test_owner_and_the_assigned_technician_can_both_clock_in_on_the_same_job(client):
    """A job has one assigned technician, but office staff (owner/admin/
    office) may also act on any job -- so the unique-open-entry constraint is
    keyed per (job, technician_id) of the ACTOR, not just the job's single
    assignee, and two different actors clocking in on the same job must not
    collide."""
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)
    client.post(
        f"/api/v1/jobs/{job}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    assert _clock_in(client, tech, job).status_code == 201
    assert _clock_in(client, owner, job).status_code == 201

    entries = client.get(
        f"/api/v1/jobs/{job}/time-entries", headers=auth_headers(owner)
    ).json()
    assert len(entries) == 2
    assert {e["technician_id"] for e in entries} == {
        tech["user"]["id"], owner["user"]["id"],
    }


def test_an_unassigned_technician_cannot_clock_in(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)

    assert _clock_in(client, tech, job).status_code == 403


def test_clock_in_on_unknown_job_is_404(client):
    owner = signup(client)
    assert _clock_in(client, owner, str(uuid.uuid4())).status_code == 404


def test_tenant_isolation_of_time_entries(client):
    owner_a = signup(client, company_name="Acme Marine")
    job_a = _job(client, owner_a)
    _clock_in(client, owner_a, job_a)

    owner_b = signup(client, company_name="Bayside Yachts")
    assert _clock_in(client, owner_b, job_a).status_code == 404
    assert client.get(
        f"/api/v1/jobs/{job_a}/time-entries", headers=auth_headers(owner_b)
    ).status_code == 404
