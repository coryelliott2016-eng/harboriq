"""Offline queue age / idempotency-replay audit — marine threat model Scenario 3."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import auth_headers, signup
from tests.test_crm_jobs import make_customer, make_job


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _clock_in(client, actor, job_id, **fields):
    return client.post(
        f"/api/v1/jobs/{job_id}/clock-in", json=fields, headers=auth_headers(actor)
    )


def test_clock_in_rejects_client_queued_at_too_old(client):
    owner = signup(client)
    job = _job(client, owner)
    too_old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    resp = _clock_in(
        client,
        owner,
        job,
        idempotency_key=str(uuid.uuid4()),
        client_queued_at=too_old,
    )
    assert resp.status_code == 422, resp.text
    assert "too old" in resp.json()["detail"].lower()


def test_clock_in_rejects_client_queued_at_far_future(client):
    owner = signup(client)
    job = _job(client, owner)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = _clock_in(
        client,
        owner,
        job,
        idempotency_key=str(uuid.uuid4()),
        client_queued_at=future,
    )
    assert resp.status_code == 422, resp.text
    assert "future" in resp.json()["detail"].lower()


def test_clock_in_accepts_recent_client_queued_at(client):
    owner = signup(client)
    job = _job(client, owner)
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    resp = _clock_in(
        client,
        owner,
        job,
        idempotency_key=str(uuid.uuid4()),
        client_queued_at=recent,
    )
    assert resp.status_code == 201, resp.text


def test_idempotency_replay_still_returns_original(client):
    owner = signup(client)
    job = _job(client, owner)
    key = str(uuid.uuid4())
    first = _clock_in(client, owner, job, idempotency_key=key)
    assert first.status_code == 201, first.text
    second = _clock_in(client, owner, job, idempotency_key=key)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
