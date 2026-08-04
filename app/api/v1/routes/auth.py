"""Authentication + tenant onboarding endpoints.

Unauthenticated: signup, login, refresh, password-reset request/confirm.
Authenticated:   me, logout, users (owner/admin only).
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
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    get_current_principal,
    get_current_user,
    get_db,
    get_service_db,
    require_user_manager,
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
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import AuthenticatedUser
from app.services.outbox_dispatch import dispatch_outbox_soon

router = APIRouter(prefix="/auth", tags=["auth"])


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
    user: AuthenticatedUser, tokens: auth_service.IssuedTokens
) -> AuthResponse:
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
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    request: Request,
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (auth_service.EmailAlreadyRegistered, auth_service.CompanySlugTaken) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _auth_response(user, tokens)


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
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
    except auth_service.AccountLocked as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except auth_service.InvalidCredentials as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _auth_response(user, tokens)


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
    service_db: Session = Depends(get_service_db),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
):
    """Exchange a refresh token for a new pair. The old token is invalidated."""
    try:
        user, tokens = auth_service.refresh(
            db,
            service_db,
            raw_refresh_token=body.refresh_token,
            ip=_client_ip(request),
            user_agent=user_agent,
        )
    except auth_service.InvalidRefreshToken as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _auth_response(user, tokens)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    body: LogoutRequest,
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except auth_service.InviteNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except auth_service.EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _auth_response(user, tokens)
