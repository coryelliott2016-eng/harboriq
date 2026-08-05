"""Authentication + tenant onboarding endpoints.

Unauthenticated: signup, login, refresh, password-reset request/confirm.
Authenticated:   me, logout, users (owner/admin only).

Phase 16 -- refresh-token transport: the refresh token is now set as an
httpOnly cookie (`REFRESH_COOKIE_NAME`) rather than returned in the JSON
response body / stored in frontend localStorage. Every endpoint that used to
return a `refresh_token` field now calls `_set_refresh_cookie` instead; only
the access token still travels in the JSON body (`TokenPair.access_token`),
unchanged. `POST /auth/refresh` reads the cookie via `request.cookies`, not
a request body -- there is no `RefreshRequest` schema anymore.

Cookie attributes: `httponly=True` (never readable by frontend JS -- the
whole point), `samesite="lax"` (NOT `"strict"`: this app's frontend and API
are configured as separate origins in every deployment topology documented
in README/DEPLOYMENT.md -- e.g. a Vite dev server on :5173 talking to the
API on :8000, or a static frontend host talking to a separately-hosted API
in production -- and `SameSite=Strict` would silently drop the cookie on
the very first cross-site request after a fresh navigation, breaking
`AuthContext`'s session-hydration-on-load flow; `Lax` still blocks the
classic cross-site POST forgery case), `secure=True` outside local plain-HTTP
development (see `_cookie_is_secure`). CSRF: `app/core/csrf.py` adds a
double-submit token on top of SameSite=Lax as defense-in-depth -- see that
module's docstring for why SameSite alone was not considered sufficient.
"""
from __future__ import annotations

from ipaddress import ip_address

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_current_principal,
    get_current_user,
    get_db,
    get_service_db,
    require_user_manager,
)
from app.core.config import settings
from app.core.csrf import (
    clear_csrf_cookie,
    new_csrf_token,
    set_csrf_cookie,
    verify_csrf,
)
from app.core.rate_limit import (
    enforce_login_rate_limit,
    enforce_password_reset_rate_limit,
)
from app.core.security import WeakPassword
from app.schemas.auth import (
    AcceptInviteRequest,
    AuthResponse,
    CreateInviteRequest,
    CreateUserRequest,
    InviteOut,
    InvitePreviewOut,
    LoginMfaRequest,
    LoginMfaRequiredResponse,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)
from app.services import auth as auth_service
from app.services import mfa as mfa_service
from app.services.auth import AuthenticatedUser
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(prefix="/auth", tags=["auth"])

#: Name of the httpOnly cookie carrying the opaque refresh token. Distinct
#: from `app.core.csrf.CSRF_COOKIE_NAME`, which is intentionally readable.
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _cookie_is_secure() -> bool:
    """Whether to set the `Secure` cookie attribute.

    `Secure` cookies are only ever sent over HTTPS -- correct and required
    in any real deployment, but it also means the cookie is silently
    dropped by a browser talking to a plain-HTTP `localhost` dev server,
    which would break local development entirely. Gated on `app_env`, the
    same signal `config.py` already uses to distinguish "a real deployment"
    from "someone's laptop" (see `_require_strong_jwt_secret_outside_development`).
    """
    return settings.app_env != "development"


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=_cookie_is_secure(),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
    )
    # Paired double-submit CSRF cookie -- see app/core/csrf.py. Scoped to the
    # same path as the refresh cookie it protects; the wider app does not
    # need to read it.
    set_csrf_cookie(response, new_csrf_token(), secure=_cookie_is_secure())


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    clear_csrf_cookie(response)


def _dispatch_outbox_soon(background_tasks: BackgroundTasks) -> None:
    """Schedule near-real-time outbox delivery. See `outbox_dispatch` module."""
    dispatch_outbox_soon(background_tasks)


def _client_ip(request: Request) -> str | None:
    """The peer address, or None when it is not a real IP.

    `request.client.host` is whatever the transport reports, which for a unix
    socket or an in-process test client is not an address at all. The audit
    columns are `inet`, so anything unparseable is dropped rather than allowed
    to fail the request it was only meant to annotate.
    """
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None


def _auth_response(
    response: Response, user: AuthenticatedUser, tokens: auth_service.IssuedTokens
) -> AuthResponse:
    """Build the JSON body AND set the refresh/CSRF cookies on `response`.

    Every caller passes the `Response` FastAPI injected into the route
    handler (not a freshly-constructed one) so the `Set-Cookie` headers this
    adds land on the actual outgoing response rather than being discarded.
    """
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(
        user=UserOut(
            id=str(user.id),
            company_id=str(user.company_id),
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
        ),
        tokens=TokenPair(
            access_token=tokens.access_token,
            expires_in=tokens.expires_in,
        ),
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Create a new company (tenant) plus its first owner user, and log in."""
    try:
        user, tokens = auth_service.signup(
            db,
            service_db,
            company_name=body.company_name,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            company_slug=body.company_slug,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (auth_service.EmailAlreadyRegistered, auth_service.CompanySlugTaken) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _auth_response(response, user, tokens)


@router.post("/login", response_model=None)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Password login. Returns `LoginMfaRequiredResponse` (still HTTP 200,
    but a different JSON shape — see `mfa_required` field) instead of
    `AuthResponse` when the account has MFA active; the client must then
    call `POST /auth/login/mfa` with the returned `pre_auth_token` plus a
    TOTP/backup code before it gets real tokens. Modeled as a 200 with a
    distinct body rather than a 4xx because nothing about the request was
    wrong — the password WAS correct — so a 2xx accurately reflects that,
    while `response_model` is left off this branch (returned as a plain
    dict) so FastAPI does not try to coerce it into `AuthResponse`.
    """
    # In-process, per-IP fixed-window limit (see app/core/rate_limit.py) —
    # a speed bump ahead of the real security control, which is the
    # per-account lockout inside auth_service.login itself.
    enforce_login_rate_limit(request)
    try:
        user, tokens = auth_service.login(
            db,
            service_db,
            email=body.email,
            password=body.password,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except auth_service.MfaRequired as exc:
        return LoginMfaRequiredResponse(pre_auth_token=exc.pre_auth_token).model_dump()
    except auth_service.AccountLocked as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except auth_service.InvalidCredentials as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _auth_response(response, user, tokens).model_dump()


@router.post("/login/mfa", response_model=AuthResponse)
def login_mfa(
    body: LoginMfaRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Second step of an MFA login: pre-auth token + TOTP/backup code -> real tokens.

    Reuses the SAME per-IP login rate limit as `POST /auth/login` — this
    endpoint is just as attackable (guessing a 6-digit TOTP code, or brute-
    forcing a backup code) as a password, so it gets the same speed bump.
    """
    enforce_login_rate_limit(request)
    try:
        user, tokens = auth_service.login_mfa(
            db,
            pre_auth_token=body.pre_auth_token,
            code=body.code,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except auth_service.InvalidMfaPreAuthToken as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired MFA session; please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except mfa_service.InvalidMfaCode as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except mfa_service.MfaNotEnabled as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except auth_service.InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return _auth_response(response, user, tokens)


def _unauthorized_and_clear_cookies(response: Response, detail: str) -> JSONResponse:
    """401 response that also clears the refresh/CSRF cookies.

    Building the `JSONResponse` directly (copying over cookies already
    queued on the injected `response`, if any, plus the WWW-Authenticate
    header) is what makes clearing survive -- see the `refresh` docstring.
    """
    _clear_refresh_cookie(response)
    out = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )
    for key, value in response.raw_headers:
        if key.decode("latin-1").lower() == "set-cookie":
            out.raw_headers.append((key, value))
    return out


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Exchange a refresh token for a new pair. The old token is invalidated.

    Phase 16: the refresh token is read from the httpOnly cookie
    (`REFRESH_COOKIE_NAME`), never from the request body -- there is nothing
    for frontend JS to send explicitly, which is the point of an httpOnly
    cookie. `verify_csrf` enforces the double-submit CSRF check first (see
    `app/core/csrf.py`) since this endpoint's whole job is "do something
    because a cookie says so", exactly the shape CSRF protection exists for.

    On failure this returns a `JSONResponse` directly (rather than raising
    `HTTPException`) so the `_clear_refresh_cookie` mutation actually reaches
    the client: FastAPI's exception handling builds a brand-new response for
    a raised `HTTPException`, discarding whatever headers were already set
    on the dependency-injected `Response` object -- returning a response
    explicitly is the only way to guarantee a Set-Cookie header survives a
    401 here.
    """
    verify_csrf(request)
    raw_refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_refresh_token:
        return _unauthorized_and_clear_cookies(response, "no refresh token cookie")
    try:
        user, tokens = auth_service.refresh(
            db,
            service_db,
            raw_refresh_token=raw_refresh_token,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except auth_service.InvalidRefreshToken:
        return _unauthorized_and_clear_cookies(response, "invalid refresh token")
    return _auth_response(response, user, tokens)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    body: LogoutRequest,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Revoke this device's refresh tokens (or every device's)."""
    revoked = auth_service.logout(
        db,
        company_id=principal.user.company_id,
        user_id=principal.user.id,
        session_id=principal.session_id,
        all_devices=body.all_devices,
    )
    _clear_refresh_cookie(response)
    return LogoutResponse(revoked_sessions=revoked)


@router.get("/me", response_model=UserOut)
def me(user: AuthenticatedUser = Depends(get_current_user)):
    return UserOut(
        id=str(user.id),
        company_id=str(user.company_id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
):
    """Provision a user inside the caller's company. Owner/admin only."""
    try:
        user = auth_service.create_user(
            db,
            company_id=actor.company_id,
            actor_user_id=actor.id,
            actor_role=actor.role,
            email=body.email,
            password=body.password,
            role=body.role.value,
            full_name=body.full_name,
            ip=_client_ip(request),
        )
    except WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except auth_service.RoleNotPermitted as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except auth_service.EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return UserOut(
        id=str(user.id),
        company_id=str(user.company_id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(
    body: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
):
    """Queue a reset email. Always 202 — never reveals whether the email exists."""
    enforce_password_reset_rate_limit(request)
    auth_service.request_password_reset(
        db, service_db, email=body.email, ip=_client_ip(request)
    )
    _dispatch_outbox_soon(background_tasks)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_confirm(
    body: PasswordResetConfirm,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
):
    """Consume a reset token, set the new password, and revoke every session."""
    try:
        auth_service.confirm_password_reset(
            db, service_db, raw_token=body.token, new_password=body.new_password
        )
    except WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except auth_service.InvalidResetToken as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# invite-link user provisioning
# ---------------------------------------------------------------------------
@router.post(
    "/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
def create_invite(
    body: CreateInviteRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    actor: AuthenticatedUser = Depends(require_user_manager),
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
):
    """Issue an invite link for a new teammate. Owner/admin only.

    Same role-escalation rule as `POST /auth/users` (an admin cannot invite
    an owner) and the same 409-on-duplicate-email rule as signup — checked
    up front here so the invitee never fills out a password only to be told
    at the end that the address was already taken.
    """
    try:
        invite = auth_service.create_invite(
            db,
            service_db,
            company_id=actor.company_id,
            actor_user_id=actor.id,
            actor_role=actor.role,
            email=body.email,
            role=body.role.value,
            full_name=body.full_name,
            ip=_client_ip(request),
        )
    except auth_service.RoleNotPermitted as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except auth_service.EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    _dispatch_outbox_soon(background_tasks)
    return InviteOut(**invite)


@router.get("/invites/{token}", response_model=InvitePreviewOut)
def get_invite(
    token: str,
    service_db: Session = Depends(get_service_db),
):
    """Unauthenticated preview for the accept-invite page: who/what/where.

    Read-only — does not consume the invite. 404 for unknown, expired,
    revoked, or already-used tokens; the message never distinguishes those
    cases from each other, the same enumeration-avoidance stance the
    password-reset and invoice pay-link endpoints already take.
    """
    try:
        preview = auth_service.get_invite(service_db, token)
    except auth_service.InviteNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return InvitePreviewOut(**preview)


@router.post("/invites/{token}/accept", response_model=AuthResponse)
def accept_invite(
    token: str,
    body: AcceptInviteRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Consume an invite, create the account, and log the new user straight in."""
    try:
        user, tokens = auth_service.accept_invite(
            db,
            service_db,
            raw_token=token,
            password=body.password,
            full_name=body.full_name,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except WeakPassword as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except auth_service.InviteNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except auth_service.EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _auth_response(response, user, tokens)
