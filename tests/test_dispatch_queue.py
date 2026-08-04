"""`GET /jobs?sort=priority_score` — the AI-dispatch-ordered work queue."""
from __future__ import annotations

from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _recompute(client, actor, job_id):
    resp = client.post(
        f"/api/v1/jobs/{job_id}/dispatch/recompute", headers=auth_headers(actor)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_queue_orders_by_cached_dispatch_score_descending(client):
    owner = signup(client)
    customer = make_customer(client, owner)

    low = make_job(client, owner, customer, title="Routine checkup", priority="low").json()
    urgent = make_job(
        client, owner, customer, title="Engine won't start", priority="urgent"
    ).json()
    normal = make_job(client, owner, customer, title="Bottom paint", priority="normal").json()

    for job in (low, urgent, normal):
        _recompute(client, owner, job["id"])

    resp = client.get(
        "/api/v1/jobs", params={"sort": "priority_score"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    ids_in_order = [j["id"] for j in resp.json()]

    assert ids_in_order.index(urgent["id"]) < ids_in_order.index(normal["id"])
    assert ids_in_order.index(normal["id"]) < ids_in_order.index(low["id"])


def test_unscored_jobs_sort_last_in_the_priority_queue(client):
    owner = signup(client)
    customer = make_customer(client, owner)

    scored = make_job(client, owner, customer, priority="urgent").json()
    _recompute(client, owner, scored["id"])

    unscored = make_job(client, owner, customer, priority="urgent").json()

    resp = client.get(
        "/api/v1/jobs", params={"sort": "priority_score"}, headers=auth_headers(owner)
    )
    ids_in_order = [j["id"] for j in resp.json()]
    assert ids_in_order.index(scored["id"]) < ids_in_order.index(unscored["id"])


def test_default_sort_is_unchanged_scheduled_at_behaviour(client):
    owner = signup(client)
    customer = make_customer(client, owner)
    job = make_job(client, owner, customer).json()

    resp = client.get("/api/v1/jobs", headers=auth_headers(owner))
    assert resp.status_code == 200
    assert any(j["id"] == job["id"] for j in resp.json())


def test_invalid_sort_value_is_rejected(client):
    owner = signup(client)
    resp = client.get(
        "/api/v1/jobs", params={"sort": "nonsense"}, headers=auth_headers(owner)
    )
    assert resp.status_code == 422
