"""MFA / TOTP enrollment, confirm, disable, and login second-factor flow.

Covers: enroll -> confirm -> login now requires a second factor -> backup
codes work and are single-use -> disable requires password re-entry ->
tenant/user isolation of both the TOTP secret and backup codes.
"""
from __future__ import annotations

import pyotp

from tests.conftest import DEFAULT_PASSWORD, auth_headers, signup, unique_email


def _enroll(client, actor: dict) -> dict:
    resp = client.post("/api/v1/users/me/mfa/enroll", headers=auth_headers(actor))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _confirm(client, actor: dict, secret: str) -> dict:
    code = pyotp.TOTP(secret).now()
    resp = client.post(
        "/api/v1/users/me/mfa/confirm",
        json={"code": code},
        headers=auth_headers(actor),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll_and_confirm(client, actor: dict) -> tuple[str, list[str]]:
    """Full enroll+confirm; returns (secret, backup_codes)."""
    enrolled = _enroll(client, actor)
    confirmed = _confirm(client, actor, enrolled["secret"])
    return enrolled["secret"], confirmed["backup_codes"]


# ---------------------------------------------------------------------------
# enroll / confirm
# ---------------------------------------------------------------------------
def test_enroll_returns_otpauth_uri_and_secret(client):
    owner = signup(client)
    body = _enroll(client, owner)
    assert body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["secret"] in body["otpauth_uri"]


def test_confirm_with_wrong_code_is_rejected_and_does_not_activate(client):
    owner = signup(client)
    _enroll(client, owner)
    resp = client.post(
        "/api/v1/users/me/mfa/confirm",
        json={"code": "000000"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 401, resp.text

    status_resp = client.get("/api/v1/users/me/mfa", headers=auth_headers(owner))
    assert status_resp.json()["mfa_enabled"] is False


def test_confirm_with_correct_code_activates_mfa_and_issues_backup_codes(client):
    owner = signup(client)
    secret, codes = _enroll_and_confirm(client, owner)

    assert len(codes) == 10
    assert len(set(codes)) == 10  # all unique

    status_resp = client.get("/api/v1/users/me/mfa", headers=auth_headers(owner))
    body = status_resp.json()
    assert body["mfa_enabled"] is True
    assert body["remaining_backup_codes"] == 10


def test_confirm_without_a_pending_enrollment_is_rejected(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/users/me/mfa/confirm",
        json={"code": "123456"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 400, resp.text


def test_enroll_again_while_already_enabled_is_rejected(client):
    owner = signup(client)
    _enroll_and_confirm(client, owner)

    resp = client.post("/api/v1/users/me/mfa/enroll", headers=auth_headers(owner))
    assert resp.status_code == 409, resp.text


def test_re_enroll_before_confirming_replaces_the_pending_secret(client):
    owner = signup(client)
    first = _enroll(client, owner)
    second = _enroll(client, owner)
    assert first["secret"] != second["secret"]

    # The old (now-replaced) secret's code must no longer confirm.
    stale_code = pyotp.TOTP(first["secret"]).now()
    resp = client.post(
        "/api/v1/users/me/mfa/confirm",
        json={"code": stale_code},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 401, resp.text

    # The current secret's code does.
    fresh_code = pyotp.TOTP(second["secret"]).now()
    resp2 = client.post(
        "/api/v1/users/me/mfa/confirm",
        json={"code": fresh_code},
        headers=auth_headers(owner),
    )
    assert resp2.status_code == 200, resp2.text


# ---------------------------------------------------------------------------
# login second-factor
# ---------------------------------------------------------------------------
def test_login_without_mfa_active_returns_real_tokens_directly(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "tokens" in body
    assert "mfa_required" not in body


def test_login_with_mfa_active_requires_second_factor(client):
    owner = signup(client)
    _enroll_and_confirm(client, owner)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mfa_required"] is True
    assert body["pre_auth_token"]
    assert "tokens" not in body
    # No refresh cookie should be set yet — the login is not complete.
    assert "refresh_token" not in resp.cookies


def test_login_mfa_with_correct_totp_code_issues_real_tokens(client):
    owner = signup(client)
    secret, _codes = _enroll_and_confirm(client, owner)

    first = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    pre_auth_token = first.json()["pre_auth_token"]

    resp = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": pre_auth_token, "code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tokens"]["access_token"]
    assert "refresh_token" in resp.cookies


def test_login_mfa_with_wrong_code_is_rejected(client):
    owner = signup(client)
    _enroll_and_confirm(client, owner)

    first = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    pre_auth_token = first.json()["pre_auth_token"]

    resp = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": pre_auth_token, "code": "000000"},
    )
    assert resp.status_code == 401, resp.text


def test_login_mfa_with_garbage_pre_auth_token_is_rejected(client):
    resp = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": "not-a-real-token", "code": "123456"},
    )
    assert resp.status_code == 401, resp.text


def test_a_normal_access_token_is_not_accepted_as_a_pre_auth_token(client):
    """The pre-auth token and access token are distinct JWT `typ`s — an
    already-authenticated user's real access token must not work here."""
    owner = signup(client)
    resp = client.post(
        "/api/v1/auth/login/mfa",
        json={
            "pre_auth_token": owner["tokens"]["access_token"],
            "code": "123456",
        },
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# backup codes
# ---------------------------------------------------------------------------
def test_backup_code_logs_in_and_is_then_single_use(client):
    owner = signup(client)
    _secret, codes = _enroll_and_confirm(client, owner)
    one_code = codes[0]

    first = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    pre_auth_token = first.json()["pre_auth_token"]

    resp = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": pre_auth_token, "code": one_code},
    )
    assert resp.status_code == 200, resp.text

    # Remaining count dropped by exactly one.
    status_resp = client.get("/api/v1/users/me/mfa", headers=auth_headers(owner))
    assert status_resp.json()["remaining_backup_codes"] == 9

    # Re-using the same code fails, even against a fresh pre-auth token.
    second = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    pre_auth_token_2 = second.json()["pre_auth_token"]
    replay = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": pre_auth_token_2, "code": one_code},
    )
    assert replay.status_code == 401, replay.text


def test_confirm_regenerates_a_fresh_full_batch_of_backup_codes(client):
    """Disable + re-enroll + re-confirm must not leave stale codes usable,
    and must always hand back a full fresh batch."""
    owner = signup(client)
    _secret, first_codes = _enroll_and_confirm(client, owner)

    resp = client.post(
        "/api/v1/users/me/mfa/disable",
        json={"password": DEFAULT_PASSWORD},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text

    secret2, second_codes = _enroll_and_confirm(client, owner)
    assert len(second_codes) == 10
    assert set(first_codes).isdisjoint(second_codes)

    # An old backup code from the first batch must not work post-re-enrollment.
    first_login = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    pre_auth_token = first_login.json()["pre_auth_token"]
    stale = client.post(
        "/api/v1/auth/login/mfa",
        json={"pre_auth_token": pre_auth_token, "code": first_codes[0]},
    )
    assert stale.status_code == 401, stale.text


# ---------------------------------------------------------------------------
# disable
# ---------------------------------------------------------------------------
def test_disable_requires_correct_password(client):
    owner = signup(client)
    _enroll_and_confirm(client, owner)

    resp = client.post(
        "/api/v1/users/me/mfa/disable",
        json={"password": "totally-wrong-password"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 401, resp.text

    status_resp = client.get("/api/v1/users/me/mfa", headers=auth_headers(owner))
    assert status_resp.json()["mfa_enabled"] is True


def test_disable_with_correct_password_deactivates_and_login_no_longer_needs_mfa(client):
    owner = signup(client)
    _enroll_and_confirm(client, owner)

    resp = client.post(
        "/api/v1/users/me/mfa/disable",
        json={"password": DEFAULT_PASSWORD},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": owner["user"]["email"], "password": DEFAULT_PASSWORD},
    )
    assert login_resp.status_code == 200
    assert "tokens" in login_resp.json()


def test_disable_when_not_enabled_is_rejected(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/users/me/mfa/disable",
        json={"password": DEFAULT_PASSWORD},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------
def test_mfa_enrollment_is_per_user_not_shared_across_a_company(client):
    owner = signup(client)
    resp = client.post(
        "/api/v1/auth/users",
        json={"email": unique_email("tech"), "password": DEFAULT_PASSWORD, "role": "technician"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    tech_email = resp.json()["email"]

    _enroll_and_confirm(client, owner)

    tech_login = client.post(
        "/api/v1/auth/login",
        json={"email": tech_email, "password": DEFAULT_PASSWORD},
    )
    assert tech_login.status_code == 200
    assert "tokens" in tech_login.json()  # no MFA required for the technician


def test_mfa_status_and_backup_codes_are_isolated_between_tenants(client):
    owner_a = signup(client)
    owner_b = signup(client, email=unique_email("ownerb"))

    _enroll_and_confirm(client, owner_a)

    status_b = client.get("/api/v1/users/me/mfa", headers=auth_headers(owner_b))
    assert status_b.json() == {"mfa_enabled": False, "remaining_backup_codes": 0}
