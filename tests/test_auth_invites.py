"""Invite-link user provisioning: POST /auth/invites, GET .../{token},
POST .../{token}/accept.

Mirrors `test_auth_rbac.py`'s guarantees for the direct `POST /auth/users`
path (role-escalation guard, tenant scoping, weak-password rejection) since
this is now the second way to provision a user and both must agree.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import DEFAULT_PASSWORD, auth_headers, signup, unique_email


def _create_invite(client, actor: dict, role: str, email: str | None = None):
    return client.post(
        "/api/v1/auth/invites",
        json={"email": email or unique_email(role), "role": role},
        headers=auth_headers(actor),
    )


def _accept_url_to_token(accept_url: str) -> str:
    return accept_url.rstrip("/").rsplit("/", 1)[-1]


@pytest.mark.parametrize("role", ["admin", "office", "technician", "owner"])
def test_an_owner_can_invite_any_role(client, role):
    owner = signup(client)
    resp = _create_invite(client, owner, role)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == role
    assert body["accept_url"]
    assert body["company_name"]


@pytest.mark.parametrize("role", ["admin", "office", "technician"])
def test_an_admin_can_invite_non_owner_roles(client, role):
    owner = signup(client)
    admin_email = unique_email("admin")
    admin_invite = _create_invite(client, owner, "admin", admin_email)
    assert admin_invite.status_code == 201
    admin = _accept(client, admin_invite.json()["accept_url"])

    resp = _create_invite(client, admin, role)
    assert resp.status_code == 201, resp.text


def test_an_admin_cannot_invite_an_owner(client):
    owner = signup(client)
    admin_email = unique_email("admin")
    admin_invite = _create_invite(client, owner, "admin", admin_email)
    admin = _accept(client, admin_invite.json()["accept_url"])

    resp = _create_invite(client, admin, "owner")
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("role", ["office", "technician"])
def test_non_managers_cannot_send_invites(client, role):
    owner = signup(client)
    invite_resp = _create_invite(client, owner, role)
    member = _accept(client, invite_resp.json()["accept_url"])

    resp = _create_invite(client, member, "technician")
    assert resp.status_code == 403, resp.text


def test_unauthenticated_callers_cannot_send_invites(client):
    resp = client.post(
        "/api/v1/auth/invites", json={"email": unique_email(), "role": "technician"}
    )
    assert resp.status_code == 401, resp.text


def test_inviting_an_already_registered_email_is_rejected(client):
    owner = signup(client)
    resp = _create_invite(client, owner, "technician", owner["user"]["email"])
    assert resp.status_code == 409, resp.text


def _accept(client, accept_url: str, password: str = DEFAULT_PASSWORD, full_name=None):
    token = _accept_url_to_token(accept_url)
    body = {"password": password}
    if full_name is not None:
        body["full_name"] = full_name
    resp = client.post(f"/api/v1/auth/invites/{token}/accept", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_invite_accept_flow_creates_a_working_logged_in_user(client):
    owner = signup(client)
    email = unique_email("tech")
    invite_resp = _create_invite(client, owner, "technician", email)
    assert invite_resp.status_code == 201
    invite = invite_resp.json()
    assert invite["email"] == email

    accepted = _accept(client, invite["accept_url"], full_name="New Tech")
    assert accepted["user"]["email"] == email
    assert accepted["user"]["role"] == "technician"
    assert accepted["user"]["company_id"] == owner["user"]["company_id"]
    assert accepted["user"]["full_name"] == "New Tech"
    assert accepted["tokens"]["access_token"]

    # The access token actually works.
    resp = client.get("/api/v1/auth/me", headers=auth_headers(accepted))
    assert resp.status_code == 200
    assert resp.json()["email"] == email

    # A normal password-based login also works afterwards.
    login_resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert login_resp.status_code == 200


def test_get_invite_preview_returns_email_role_and_company(client):
    owner = signup(client, company_name="Bayside Marine")
    email = unique_email("office")
    invite_resp = _create_invite(client, owner, "office", email)
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    resp = client.get(f"/api/v1/auth/invites/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "office"
    assert body["company_name"] == "Bayside Marine"


def test_get_invite_preview_does_not_consume_the_token(client):
    owner = signup(client)
    invite_resp = _create_invite(client, owner, "technician")
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    for _ in range(3):
        resp = client.get(f"/api/v1/auth/invites/{token}")
        assert resp.status_code == 200

    accept_resp = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": DEFAULT_PASSWORD}
    )
    assert accept_resp.status_code == 200


def test_accepting_twice_fails_the_second_time(client):
    owner = signup(client)
    invite_resp = _create_invite(client, owner, "technician")
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    first = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": DEFAULT_PASSWORD}
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": DEFAULT_PASSWORD}
    )
    assert second.status_code == 404, second.text


def test_an_unknown_token_is_404_for_both_preview_and_accept(client):
    resp = client.get("/api/v1/auth/invites/not-a-real-token")
    assert resp.status_code == 404

    resp = client.post(
        "/api/v1/auth/invites/not-a-real-token/accept",
        json={"password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 404


def test_a_revoked_or_expired_token_is_rejected(client, service_db):
    owner = signup(client)
    invite_resp = _create_invite(client, owner, "technician")
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    service_db.execute(
        text("UPDATE public_tokens SET expires_at = now() - interval '1 hour'")
    )
    service_db.commit()

    resp = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 404, resp.text


def test_accept_rejects_a_weak_password(client):
    owner = signup(client)
    invite_resp = _create_invite(client, owner, "technician")
    token = _accept_url_to_token(invite_resp.json()["accept_url"])

    resp = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": "short"}
    )
    assert resp.status_code == 422, resp.text

    # The token is still usable after a rejected accept attempt.
    resp = client.post(
        f"/api/v1/auth/invites/{token}/accept", json={"password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200


def test_invited_user_is_scoped_to_the_inviting_tenant_only(client):
    owner_a = signup(client, company_name="Tenant A")
    owner_b = signup(client, company_name="Tenant B")

    invite_resp = _create_invite(client, owner_a, "technician")
    accepted = _accept(client, invite_resp.json()["accept_url"])

    # The new user cannot see tenant B's team via /auth/me company scoping.
    assert accepted["user"]["company_id"] == owner_a["user"]["company_id"]
    assert accepted["user"]["company_id"] != owner_b["user"]["company_id"]
