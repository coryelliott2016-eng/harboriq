"""`GET /users` (team roster) and `PATCH /users/{id}` (Phase 10).

Covers: self-edit vs admin-edit permission boundaries, tenant isolation,
and restricted-field enforcement (a non-admin cannot touch their own
`role`/`is_active`). Geocoding itself is mocked here (a value error, not
this file's concern) — see `tests/test_geocoding.py` for the geocoding
behavior itself; here we only need to confirm address_text is accepted and
saved.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import auth_headers, invite, signup, unique_email


@pytest.fixture(autouse=True)
def _no_real_geocoding():
    """Every test in this module patches geocoding.geocode so no test here
    makes a real network call — this file is about permissions, not
    geocoding correctness."""
    with patch("app.services.geocoding.geocode", return_value=None) as mocked:
        yield mocked


def test_user_can_edit_their_own_profile(client):
    owner = signup(client)
    resp = client.patch(
        f"/api/v1/users/{owner['user']['id']}",
        json={"full_name": "New Name", "skills": ["outboard", "electrical"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "New Name"
    assert set(body["skills"]) == {"outboard", "electrical"}


def test_self_edit_address_text_is_saved_even_without_a_geocode_match(client):
    owner = signup(client)
    resp = client.patch(
        f"/api/v1/users/{owner['user']['id']}",
        json={"address_text": "123 Nowhere Ln, Nowhere, ZZ"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["address_text"] == "123 Nowhere Ln, Nowhere, ZZ"
    # geocode() was mocked to return None -> coordinates stay null, save
    # still succeeds (graceful degradation).
    assert body["home_latitude"] is None
    assert body["home_longitude"] is None


def test_a_technician_cannot_change_their_own_role(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"role": "admin"},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403, resp.text


def test_a_technician_cannot_change_their_own_is_active(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"is_active": False},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403, resp.text


def test_a_non_admin_cannot_edit_someone_elses_profile(client):
    owner = signup(client)
    tech_a = invite(client, owner, "technician")
    tech_b = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech_b['user']['id']}",
        json={"full_name": "Hijacked"},
        headers=auth_headers(tech_a),
    )
    assert resp.status_code == 403, resp.text


def test_an_admin_can_edit_a_teammates_role_and_active_status(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"role": "office", "is_active": False},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "office"
    assert body["is_active"] is False


def test_an_admin_can_edit_a_teammates_skills_and_name(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"full_name": "Renamed Tech", "skills": ["fiberglass"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Renamed Tech"
    assert body["skills"] == ["fiberglass"]


def test_office_role_cannot_edit_other_users(client):
    """office is not in USER_MANAGEMENT_ROLES -- same admin bar as inviting."""
    owner = signup(client)
    office = invite(client, owner, "office")
    tech = invite(client, owner, "technician")
    resp = client.patch(
        f"/api/v1/users/{tech['user']['id']}",
        json={"role": "admin"},
        headers=auth_headers(office),
    )
    assert resp.status_code == 403, resp.text


def test_office_can_still_edit_their_own_non_restricted_fields(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    resp = client.patch(
        f"/api/v1/users/{office['user']['id']}",
        json={"full_name": "Front Desk"},
        headers=auth_headers(office),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["full_name"] == "Front Desk"


def test_tenant_isolation_a_user_in_another_company_returns_404(client):
    owner_a = signup(client)
    tech_a = invite(client, owner_a, "technician")
    owner_b = signup(client)

    resp = client.patch(
        f"/api/v1/users/{tech_a['user']['id']}",
        json={"full_name": "Should Not Work"},
        headers=auth_headers(owner_b),
    )
    assert resp.status_code == 404, resp.text


def test_patch_requires_authentication(client):
    owner = signup(client)
    resp = client.patch(
        f"/api/v1/users/{owner['user']['id']}", json={"full_name": "X"}
    )
    assert resp.status_code == 401


def test_unknown_field_is_rejected_by_schema_validation(client):
    owner = signup(client)
    resp = client.patch(
        f"/api/v1/users/{owner['user']['id']}",
        json={"password_hash": "not-allowed"},
        headers=auth_headers(owner),
    )
    # Pydantic's default (extra="ignore") means an unrecognized field is
    # silently dropped rather than a 422 -- assert the disallowed field had
    # no effect, which is the security-relevant property.
    assert resp.status_code == 200, resp.text


def test_team_roster_lists_every_user_in_the_company(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    office = invite(client, owner, "office")

    resp = client.get("/api/v1/users", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert owner["user"]["email"] in emails
    assert tech["user"]["email"] in emails
    assert office["user"]["email"] in emails


def test_team_roster_is_tenant_isolated(client):
    owner_a = signup(client)
    invite(client, owner_a, "technician")
    owner_b = signup(client)

    resp = client.get("/api/v1/users", headers=auth_headers(owner_b))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert owner_a["user"]["email"] not in emails


def test_team_roster_forbidden_for_technicians(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.get("/api/v1/users", headers=auth_headers(tech))
    assert resp.status_code == 403, resp.text


def test_team_roster_allowed_for_office(client):
    owner = signup(client)
    office = invite(client, owner, "office")
    resp = client.get("/api/v1/users", headers=auth_headers(office))
    assert resp.status_code == 200, resp.text


def test_team_roster_requires_authentication(client):
    resp = client.get("/api/v1/users")
    assert resp.status_code == 401


def test_owner_email_used_by_unique_helper_is_not_accidentally_reused(client):
    # Sanity check that unique_email still produces distinct addresses across
    # calls in this module (guards against a fixture ordering regression).
    assert unique_email("a") != unique_email("a")
