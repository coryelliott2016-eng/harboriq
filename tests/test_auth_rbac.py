"""Role-based access control on the user-provisioning endpoint."""
from __future__ import annotations

import pytest

from tests.conftest import DEFAULT_PASSWORD, auth_headers, signup, unique_email


def _invite(client, actor: dict, role: str, email: str | None = None):
    return client.post(
        "/api/v1/auth/users",
        json={
            "email": email or unique_email(role),
            "password": DEFAULT_PASSWORD,
            "role": role,
        },
        headers=auth_headers(actor),
    )


def _login(client, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("role", ["admin", "office", "technician", "owner"])
def test_an_owner_can_provision_any_role(client, role):
    owner = signup(client)
    resp = _invite(client, owner, role)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == role
    assert body["company_id"] == owner["user"]["company_id"]


@pytest.mark.parametrize("role", ["admin", "office", "technician"])
def test_an_admin_can_provision_non_owner_roles(client, role):
    owner = signup(client)
    admin_email = unique_email("admin")
    assert _invite(client, owner, "admin", admin_email).status_code == 201
    admin = _login(client, admin_email)

    assert _invite(client, admin, role).status_code == 201


def test_an_admin_cannot_escalate_to_owner(client):
    owner = signup(client)
    admin_email = unique_email("admin")
    _invite(client, owner, "admin", admin_email)
    admin = _login(client, admin_email)

    resp = _invite(client, admin, "owner")
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["office", "technician"])
def test_non_managers_cannot_provision_users(client, role):
    owner = signup(client)
    email = unique_email(role)
    _invite(client, owner, role, email)
    actor = _login(client, email)

    resp = _invite(client, actor, "technician")
    assert resp.status_code == 403
    assert "requires one of these roles" in resp.json()["detail"]


def test_provisioning_requires_authentication(client):
    resp = client.post(
        "/api/v1/auth/users",
        json={"email": unique_email(), "password": DEFAULT_PASSWORD, "role": "technician"},
    )
    assert resp.status_code == 401


def test_provisioning_rejects_an_unknown_role(client):
    owner = signup(client)
    resp = _invite(client, owner, "superuser")
    assert resp.status_code == 422


def test_provisioning_rejects_an_email_used_by_another_tenant(client):
    other = signup(client)
    owner = signup(client)
    resp = _invite(client, owner, "technician", other["user"]["email"])
    assert resp.status_code == 409


def test_provisioning_rejects_a_weak_password(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/auth/users",
        json={"email": unique_email(), "password": "short", "role": "technician"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_a_provisioned_user_can_log_in_and_is_scoped_to_the_tenant(client):
    owner = signup(client)
    email = unique_email("tech")
    _invite(client, owner, "technician", email)

    tech = _login(client, email)
    assert tech["user"]["company_id"] == owner["user"]["company_id"]
    assert tech["user"]["role"] == "technician"

    me = client.get("/api/v1/auth/me", headers=auth_headers(tech))
    assert me.status_code == 200
    assert me.json()["role"] == "technician"


def test_a_role_change_takes_effect_without_reissuing_the_token(client, service_db):
    """Authorization reads the DB row, so demotion is immediate."""
    from sqlalchemy import text

    owner = signup(client)
    admin_email = unique_email("admin")
    created = _invite(client, owner, "admin", admin_email).json()
    admin = _login(client, admin_email)
    assert _invite(client, admin, "technician").status_code == 201

    service_db.execute(
        text("UPDATE users SET role = 'technician' WHERE id = :uid"),
        {"uid": created["id"]},
    )
    service_db.commit()

    assert _invite(client, admin, "technician").status_code == 403
