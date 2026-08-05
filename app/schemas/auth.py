import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import UserRole


class SignupRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    full_name: str | None = Field(default=None, max_length=200)
    # Optional vanity slug; generated from company_name when omitted.
    company_slug: str | None = Field(default=None, min_length=1, max_length=50)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class LogoutRequest(BaseModel):
    all_devices: bool = False


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    role: UserRole = UserRole.TECHNICIAN
    full_name: str | None = Field(default=None, max_length=200)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool


class TeamMemberOut(BaseModel):
    """Returned by `GET /users` (team roster) and `PATCH /users/{id}`.

    Superset of `UserOut` with the Phase 10 profile fields. Kept as a
    separate model rather than widening `UserOut` itself so the auth
    endpoints (`/auth/me`, `/auth/login`, etc.) keep their existing,
    already-relied-upon response shape unchanged.
    """

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    skills: list[str] = Field(default_factory=list)
    address_text: str | None = None
    #: Decimal fields are serialized as JSON strings, matching every other
    #: Decimal field in this codebase (Pydantic's default encoding) — see
    #: `app/schemas/dispatch.py`'s comment on the same pattern.
    home_latitude: Decimal | None = None
    home_longitude: Decimal | None = None
    #: Pay rate (Phase 14, migration 0013) -- admin-only, nullable. Feeds
    #: `GET /reports/pnl`'s labor-cost line; a technician with no rate set
    #: here shows as "labor cost unavailable" in that report, never $0.
    hourly_rate: Decimal | None = None


class UserUpdate(BaseModel):
    """`PATCH /users/{id}` body.

    Every field is optional (partial update); which fields the caller may
    actually set depends on whether they are editing themselves or acting
    as an admin — see `app/services/users.py::update_profile`. All fields
    use pydantic's `exclude_unset` sentinel behavior: a field the client
    never sent is simply absent from `model_dump(exclude_unset=True)`,
    distinct from a field explicitly sent as `null`.
    """

    full_name: str | None = Field(default=None, max_length=200)
    skills: list[str] | None = None
    #: Raw one-line home address; set to "" or null to clear both the
    #: address and any previously-geocoded coordinates.
    address_text: str | None = Field(default=None, max_length=500)
    role: UserRole | None = None
    is_active: bool | None = None
    #: Admin-only (see ADMIN_ONLY_COLUMNS); a technician may not set their
    #: own pay rate, matching the existing role/is_active restriction.
    hourly_rate: Decimal | None = Field(default=None, ge=0)


class TokenPair(BaseModel):
    """Access-token half of a session (Phase 16).

    `refresh_token` was removed from this JSON body -- the refresh token is
    now set as an httpOnly cookie by the backend (see
    `app/api/v1/routes/auth.py`'s `_set_refresh_cookie`) and is never visible
    to frontend JavaScript, so it has no reason to also appear here. Every
    signup/login/refresh/accept-invite response still returns exactly one
    access token in this shape; only its transport for the refresh token
    changed.
    """

    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth2 token-type literal, not a credential
    expires_in: int


class AuthResponse(BaseModel):
    """Returned by signup / login / refresh."""

    user: UserOut
    tokens: TokenPair


class LogoutResponse(BaseModel):
    revoked_sessions: int


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.TECHNICIAN
    full_name: str | None = Field(default=None, max_length=200)


class InviteOut(BaseModel):
    """Returned by `POST /auth/invites`.

    Includes the raw accept URL in the response body — the same judgement
    call `send_invoice` already makes for its pay link (see
    `InvoiceSendResponse.pay_url`): there is no task queue/worker UI yet for
    the actor to go re-fetch it from, and the actor is a trusted admin who
    just requested this invite, so handing them the link directly (to paste
    into Slack/email themselves if delivery is slow) is a reasonable MVP
    trade-off, not a security regression — the link is only useful to
    whoever already holds it.
    """

    email: str
    role: str
    full_name: str | None
    company_name: str
    expires_in_hours: int
    accept_url: str


class InvitePreviewOut(BaseModel):
    """Returned by `GET /auth/invites/{token}` for the accept-invite page."""

    email: str
    role: str
    full_name: str | None
    company_name: str


class AcceptInviteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    full_name: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# MFA / TOTP (Phase 16)
# ---------------------------------------------------------------------------
class MfaEnrollResponse(BaseModel):
    """Returned by `POST /users/me/mfa/enroll`.

    `otpauth_uri` is what `qrcode.react` renders into a scannable QR code;
    `secret` is the same value in plain base32 for manual entry when
    scanning isn't possible. Neither is retrievable again after this call —
    only the encrypted form (`users.mfa_secret_enc`) persists server-side.
    """

    otpauth_uri: str
    secret: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class MfaConfirmResponse(BaseModel):
    """Returned by `POST /users/me/mfa/confirm`. `backup_codes` is shown
    exactly once — the client should prompt the user to save/print them."""

    mfa_enabled: bool = True
    backup_codes: list[str]


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class CompanyMfaPolicyUpdate(BaseModel):
    """Body for `PATCH /companies/me/mfa-policy` (Phase 17, Area C.2)."""

    mfa_required: bool


class CompanyMfaPolicyOut(BaseModel):
    mfa_required: bool


class MfaStatusOut(BaseModel):
    """Returned by `GET /users/me/mfa`."""

    mfa_enabled: bool
    remaining_backup_codes: int


class LoginMfaRequiredResponse(BaseModel):
    """Returned by `POST /auth/login` INSTEAD OF `AuthResponse` when the
    account has MFA active — no access/refresh tokens are issued yet."""

    mfa_required: bool = True
    pre_auth_token: str


class LoginMfaEnrollmentRequiredResponse(BaseModel):
    """Returned by `POST /auth/login` (Phase 17, Area C.2) INSTEAD OF
    `AuthResponse` when the company mandates MFA (`companies.mfa_required`)
    and this user has not enrolled it yet. Deliberately has no
    `pre_auth_token` — unlike `LoginMfaRequiredResponse`, there is no
    second factor to verify yet, only an enrollment gap the user (or an
    admin, on their behalf) must close first."""

    mfa_required: bool = True
    mfa_enrollment_required: bool = True


class LoginMfaRequest(BaseModel):
    pre_auth_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=64)
