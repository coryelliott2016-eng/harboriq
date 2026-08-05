"""CSRF mitigation for the httpOnly refresh-token cookie (Phase 16).

Why this exists at all: once the refresh token moves into an httpOnly
cookie (see `app/api/v1/routes/auth.py`), the browser attaches that cookie
automatically to any request to the API's origin -- including one triggered
by a malicious third-party page the user happens to have open, via a plain
HTML form POST or `fetch(..., {credentials: "include"})`. `SameSite=Lax`
(the cookie attribute this app uses -- see the module docstring in
`auth.py` for why `Strict` was rejected) already blocks the classic
cross-site form-POST case, but Lax still allows the cookie on cross-site
*GET* navigations and, in some browsers/edge cases, top-level POST
navigations shortly after such a navigation. Belt-and-suspenders, this
module adds the standard double-submit-cookie pattern on top of SameSite
rather than relying on SameSite alone: a second, NON-httpOnly cookie holds
a random CSRF token; the frontend reads it (JS can read this one, unlike
the refresh-token cookie) and echoes it back in an `X-CSRF-Token` header on
every request that relies on the refresh cookie. A cross-site attacker can
make the browser SEND the refresh cookie automatically, but cannot READ
`document.cookie` for this app's origin to forge the matching header
(same-origin policy) -- so the two must match for `/auth/refresh` to
succeed.

This token is intentionally NOT a secret the server needs to remember: its
only job is proving the request originated from JavaScript that could read
this origin's cookies, i.e. same-origin JavaScript. Comparing the cookie
value against the header value (constant-time, to avoid a timing
side-channel) is the whole check.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Set the readable (non-httpOnly) CSRF cookie alongside the refresh cookie.

    Deliberately NOT httpOnly -- frontend JavaScript must be able to read
    this value to echo it back in the `X-CSRF-Token` header. `SameSite=Lax`
    matches the refresh-token cookie's own attribute (see `auth.py`); `Secure`
    mirrors it too, controlled by the same "are we on plain HTTP in local
    dev" flag rather than a separate decision.
    """
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=secure,
        samesite="lax",
        # Path="/" (not scoped to /api/v1/auth like the refresh cookie it
        # protects): frontend JS reading this cookie via `document.cookie`
        # runs on whatever page the user is on, not just auth pages, and
        # must be able to see it to build the `X-CSRF-Token` header for the
        # refresh call made from `api.ts`.
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")


def verify_csrf(request: Request) -> None:
    """Raise 403 unless the CSRF cookie and `X-CSRF-Token` header match.

    Called by any endpoint that relies on the httpOnly refresh cookie
    (`/auth/refresh` today). Both values must be present -- a request with
    the cookie but no header (e.g. a cross-site form POST, which cannot set
    custom headers) is rejected exactly as intended.
    """
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "missing CSRF token"
        )
    if not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "CSRF token mismatch"
        )
