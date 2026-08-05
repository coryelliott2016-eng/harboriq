"""Slips: CRUD and tenant isolation (Phase 15)."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.db.tenant import tenant_context
from tests.conftest import auth_headers, make_slip, signup


def _create_slip(client, actor, **fields):
    body = {"identifier": "A-1", "slip_type": "wet_slip", **fields}
    return client.post("/api/v1/slips", json=body, headers=auth_headers(actor))


def test_create_wet_slip_defaults(client):
    owner = signup(client)
    resp = _create_slip(client, owner)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["identifier"] == "A-1"
    assert body["slip_type"] == "wet_slip"
    assert body["status"] == "available"
    assert body["depth_ft"] is None
    assert body["rack_level"] is None


def test_create_dry_stack_slip_with_rack_fields(client):
    owner = signup(client)
    resp = _create_slip(
        client, owner,
        identifier="R-3-12", slip_type="dry_stack",
        rack_level=3, rack_position="12",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slip_type"] == "dry_stack"
    assert body["rack_level"] == 3
    assert body["rack_position"] == "12"


def test_depth_rejected_on_dry_stack(client):
    """`ck_slips_depth_only_wet_or_mooring` -- a dry-stack rack has no draft."""
    owner = signup(client)
    resp = _create_slip(client, owner, slip_type="dry_stack", depth_ft="4.5")
    assert resp.status_code == 409, resp.text


def test_rack_fields_rejected_on_wet_slip(client):
    """`ck_slips_rack_only_dry_stack` -- a wet slip has no rack position."""
    owner = signup(client)
    resp = _create_slip(client, owner, slip_type="wet_slip", rack_level=1)
    assert resp.status_code == 409, resp.text


def test_duplicate_identifier_rejected(client):
    owner = signup(client)
    first = _create_slip(client, owner, identifier="B-9")
    assert first.status_code == 201, first.text
    second = _create_slip(client, owner, identifier="B-9")
    assert second.status_code == 409, second.text


def test_lat_and_lng_must_both_be_set_or_both_omitted(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/slips",
        json={"identifier": "C-1", "slip_type": "wet_slip", "latitude": "27.33"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_list_filters_by_slip_type_and_status(client):
    owner = signup(client)
    _create_slip(client, owner, identifier="D-1", slip_type="wet_slip")
    _create_slip(client, owner, identifier="D-2", slip_type="dry_stack")

    resp = client.get("/api/v1/slips", params={"slip_type": "dry_stack"}, headers=auth_headers(owner))
    assert resp.status_code == 200
    ids = [s["identifier"] for s in resp.json()]
    assert ids == ["D-2"]


def test_update_slip_status(client):
    owner = signup(client)
    slip = _create_slip(client, owner, identifier="E-1").json()

    resp = client.patch(
        f"/api/v1/slips/{slip['id']}", json={"status": "maintenance"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "maintenance"


def test_get_unknown_slip_is_404(client):
    owner = signup(client)
    resp = client.get(f"/api/v1/slips/{uuid.uuid4()}", headers=auth_headers(owner))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------------
def test_the_api_hides_another_tenants_slip(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    theirs = _create_slip(client, b, identifier="Z-1").json()

    assert client.get(f"/api/v1/slips/{theirs['id']}", headers=auth_headers(a)).status_code == 404
    assert client.get("/api/v1/slips", headers=auth_headers(a)).json() == []


def test_the_api_refuses_to_mutate_another_tenants_slip(client):
    a = signup(client)
    b = signup(client, company_name="Bayside Yachts")
    theirs = _create_slip(client, b, identifier="Z-2").json()

    resp = client.patch(
        f"/api/v1/slips/{theirs['id']}", json={"status": "maintenance"},
        headers=auth_headers(a),
    )
    assert resp.status_code == 404


def test_db_level_tenant_isolation_on_slips(app_db, service_db, company_a, company_b):
    theirs = make_slip(service_db, company_b, identifier="Y-1")

    with tenant_context(app_db, company_a):
        row = app_db.execute(
            text("SELECT id FROM slips WHERE id = :id"), {"id": theirs}
        ).first()
    assert row is None
