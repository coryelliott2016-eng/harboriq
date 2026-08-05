"""Job attachments (photos + digital signatures) — Phase 12 field app."""
from __future__ import annotations

import base64
import uuid

from tests.conftest import auth_headers, invite, signup
from tests.test_crm_jobs import make_customer, make_job

_TINY_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg-bytes").decode()


def _job(client, actor) -> str:
    return make_job(client, actor, make_customer(client, actor)).json()["id"]


def _attach(client, actor, job_id, **fields):
    body = {"kind": "photo", "data": _TINY_JPEG_B64, **fields}
    return client.post(
        f"/api/v1/jobs/{job_id}/attachments", json=body, headers=auth_headers(actor)
    )


def test_owner_can_attach_a_photo(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _attach(client, owner, job)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "photo"
    assert body["job_id"] == job
    assert body["data"] == _TINY_JPEG_B64
    assert body["content_type"] == "image/jpeg"


def test_a_signature_can_be_attached(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _attach(client, owner, job, kind="signature", content_type="image/png")
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "signature"
    assert resp.json()["content_type"] == "image/png"


def test_a_data_url_prefix_is_stripped(client):
    owner = signup(client)
    job = _job(client, owner)

    resp = _attach(client, owner, job, data=f"data:image/jpeg;base64,{_TINY_JPEG_B64}")
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"] == _TINY_JPEG_B64


def test_attachments_list_in_upload_order(client):
    owner = signup(client)
    job = _job(client, owner)
    _attach(client, owner, job, kind="photo")
    _attach(client, owner, job, kind="signature")

    listed = client.get(
        f"/api/v1/jobs/{job}/attachments", headers=auth_headers(owner)
    ).json()
    assert [a["kind"] for a in listed] == ["photo", "signature"]


def test_idempotency_key_prevents_a_duplicate_on_replay(client):
    """The offline-sync queue may resend the same upload after a dropped
    response; a matching idempotency_key must return the original row."""
    owner = signup(client)
    job = _job(client, owner)
    key = str(uuid.uuid4())

    first = _attach(client, owner, job, idempotency_key=key)
    assert first.status_code == 201
    second = _attach(client, owner, job, idempotency_key=key)
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = client.get(
        f"/api/v1/jobs/{job}/attachments", headers=auth_headers(owner)
    ).json()
    assert len(listed) == 1


def test_different_idempotency_keys_create_separate_attachments(client):
    owner = signup(client)
    job = _job(client, owner)
    _attach(client, owner, job, idempotency_key=str(uuid.uuid4()))
    _attach(client, owner, job, idempotency_key=str(uuid.uuid4()))

    listed = client.get(
        f"/api/v1/jobs/{job}/attachments", headers=auth_headers(owner)
    ).json()
    assert len(listed) == 2


def test_the_assigned_technician_can_attach_a_photo(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)
    client.post(
        f"/api/v1/jobs/{job}/assign",
        json={"technician_id": tech["user"]["id"]},
        headers=auth_headers(owner),
    )

    assert _attach(client, tech, job).status_code == 201


def test_an_unassigned_technician_cannot_attach_a_photo(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    job = _job(client, owner)

    assert _attach(client, tech, job).status_code == 403


def test_attachment_on_unknown_job_is_404(client):
    owner = signup(client)
    resp = _attach(client, owner, str(uuid.uuid4()))
    assert resp.status_code == 404


def test_tenant_isolation_of_attachments(client):
    """A user in company A cannot see or add attachments to company B's job."""
    owner_a = signup(client, company_name="Acme Marine")
    job_a = _job(client, owner_a)
    _attach(client, owner_a, job_a)

    owner_b = signup(client, company_name="Bayside Yachts")
    # Company B's own job is unrelated; attaching to company A's job id must
    # look like "not found", not "forbidden" (RLS-backed 404, see NotFound's
    # docstring in app.services.crud).
    assert _attach(client, owner_b, job_a).status_code == 404
    assert client.get(
        f"/api/v1/jobs/{job_a}/attachments", headers=auth_headers(owner_b)
    ).status_code == 404
