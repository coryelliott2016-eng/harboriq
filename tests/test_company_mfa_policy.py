"""Admin-forced MFA policy (Phase 17, Area C.2).

Covers: default is off, only an admin/owner can toggle it, a non-admin
enforcing it is 403'd, an unenrolled user is blocked at login with a
distinct response shape (never a pre-auth token, never real tokens), and
a user who has enrolled MFA is unaffected by the policy (their normal
`MfaRequired` flow still applies).
"""
from __future__ import annotations

import pyotp

from tests.conftest import DEFAULT_PASSWORD, auth_headers, invite, signup
from tests.test_mfa import _enroll, _confirm


def test_mfa_policy_defaults_to_not_required(client):
    owner = signup(client)
    resp = client.get("/api/v1/companies/me/mfa-policy", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"mfa_required": False}


def test_owner_can_enable_mfa_policy(client):
    owner = signup(client)
    resp = client.patch(
        "/api/v1/companies/me/mfa-policy",
        json={"mfa_required": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"mfa_required": True}

    check = client.get("/api/v1/companies/me/mfa-policy", headers=auth_headers(owner))
    assert check.json() == {"mfa_required": True}


def test_non_admin_cannot_enable_mfa_policy(client):
    owner = signup(client)
    tech = invite(client, owner, "technician")
    resp = client.patch(
        "/api/v1/companies/me/mfa-policy",
        json={"mfa_required": True},
        headers=auth_headers(tech),
    )
    assert resp.status_code == 403, resp.text


def test_unenrolled_user_is_blocked_at_login_with_distinct_response(client):
    owner = signup(client)
    client.patch(
        "/api/v1/companies/me/mfa-policy",
        json={"mfa_required": True},
        headers=auth_headers(owner),
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mfa_required"] is True
    assert body.get("mfa_enrollment_required") is True
    assert "pre_auth_token" not in body
    assert "tokens" not in body


def test_enrolled_user_gets_normal_mfa_challenge_not_enrollment_block(client):
    owner = signup(client)
    enrolled = _enroll(client, owner)
    _confirm(client, owner, enrolled["secret"])

    client.patch(
        "/api/v1/companies/me/mfa-policy",
        json={"mfa_required": True},
        headers=auth_headers(owner),
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mfa_required"] is True
    assert "pre_auth_token" in body
    assert body.get("mfa_enrollment_required") is None

    # And the normal second-factor flow completes login successfully.
    code = pyotp.TOTP(enrolled["secret"]).now()
    mfa_resp = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": body["pre_auth_token"], "code": code},
    )
    assert mfa_resp.status_code == 200, mfa_resp.text
    assert "tokens" in mfa_resp.json()


def test_mfa_policy_off_does_not_block_unenrolled_login(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert "tokens" in resp.json()


def test_mfa_policy_is_scoped_per_company(client):
    owner_a = signup(client, company_name="Acme Marine")
    owner_b = signup(client, company_name="Bayside Yachts")

    client.patch(
        "/api/v1/companies/me/mfa-policy",
        json={"mfa_required": True},
        headers=auth_headers(owner_a),
    )

    # Company B is unaffected.
    resp_b = client.get("/api/v1/companies/me/mfa-policy", headers=auth_headers(owner_b))
    assert resp_b.json() == {"mfa_required": False}

    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": owner_b["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert "tokens" in login_b.json()
