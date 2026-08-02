"""Work orders: CRUD, dispatch, and the descriptive/scheduling fields."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import auth_headers, invite, signup


def make_customer(client, actor, last_name="Halyard") -> str:
    resp = client.post(
        "/api/v1/customers", json={"last_name": last_name}, headers=auth_headers(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def make_vessel(client, actor, customer_id, **fields) -> str:
    resp = client.post(
        "/api/v1/vessels",
        json={"customer_id": customer_id, "name": "Second Wind", **fields},
        headers=auth_headers(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def make_job(client, actor, customer_id, **fields):
    body = {"customer_id": customer_id, "title": "Winterize engine", **fields}
    return client.post("/api/v1/jobs", json=body, headers=auth_headers(actor))


def test_create_defaults_to_scheduled_and_normal_priority(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()
    assert job["status"] == "scheduled"
    assert job["priority"] == "normal"
    assert job["started_at"] is None
    assert job["completed_at"] is None


def test_get_returns_the_job_with_its_line_items(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.get(f"/api/v1/jobs/{job['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["line_items"] == []


def test_a_job_needs_a_title(client):
    owner = signup(client)
    customer = make_customer(client, owner)
    resp = client.post(
        "/api/v1/jobs",
        json={"customer_id": customer, "title": "   "},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_a_job_needs_a_customer_in_this_tenant(client):
    owner = signup(client)
    assert make_job(client, owner, str(uuid.uuid4())).status_code == 404


def test_the_vessel_must_belong_to_the_jobs_customer(client):
    owner = signup(client)
    mine = make_customer(client, owner, "Mine")
    theirs = make_customer(client, owner, "Theirs")
    other_boat = make_vessel(client, owner, theirs)

    resp = make_job(client, owner, mine, vessel_id=other_boat)
    assert resp.status_code == 422
    assert "does not belong" in resp.json()["detail"]


def test_a_patch_that_breaks_the_customer_vessel_pairing_is_rejected(client):
    owner = signup(client)
    mine = make_customer(client, owner, "Mine")
    theirs = make_customer(client, owner, "Theirs")
    job = make_job(client, owner, mine, vessel_id=make_vessel(client, owner, mine)).json()

    resp = client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"customer_id": theirs},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_scheduled_end_must_not_precede_the_start(client):
    owner = signup(client)
    start = datetime(2026, 5, 1, 9, tzinfo=timezone.utc)
    resp = make_job(
        client,
        owner,
        make_customer(client, owner),
        scheduled_at=start.isoformat(),
        scheduled_end_at=(start - timedelta(hours=1)).isoformat(),
    )
    assert resp.status_code == 422


def test_patch_edits_descriptive_fields(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"title": "Winterize both engines", "priority": "urgent",
              "notes": "customer waiting"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Winterize both engines"
    assert body["priority"] == "urgent"
    assert body["status"] == "scheduled"


def test_patch_cannot_set_status(client):
    """`status` is not a field of JobUpdate, so it is ignored, not applied."""
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()

    resp = client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"status": "completed"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"


def test_delete_removes_the_job_and_its_lines(client):
    owner = signup(client)
    job = make_job(client, owner, make_customer(client, owner)).json()
    client.post(
        f"/api/v1/jobs/{job['id']}/line-items",
        json={"kind": "labor", "description": "Diagnosis", "quantity": "1.00"},
        headers=auth_headers(owner),
    )

    assert client.delete(
        f"/api/v1/jobs/{job['id']}", headers=auth_headers(owner)
    ).status_code == 204
    assert client.get(
        f"/api/v1/jobs/{job['id']}", headers=auth_headers(owner)
    ).status_code == 404


def test_list_filters(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    one = make_customer(client, owner, "One")
    two = make_customer(client, owner, "Two")
    a = make_job(client, owner, one, title="A", priority="urgent").json()
    make_job(client, owner, two, title="B")
    client.post(
        f"/api/v1/jobs/{a['id']}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    def titles(**params):
        resp = client.get("/api/v1/jobs", params=params, headers=auth_headers(owner))
        assert resp.status_code == 200, resp.text
        return sorted(job["title"] for job in resp.json())

    assert titles() == ["A", "B"]
    assert titles(customer_id=one) == ["A"]
    assert titles(priority="urgent") == ["A"]
    assert titles(technician_id=tech["user"]["id"]) == ["A"]
    assert titles(unassigned="true") == ["B"]
    assert titles(status="scheduled") == ["A", "B"]
    assert titles(status="completed") == []
