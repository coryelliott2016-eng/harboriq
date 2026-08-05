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


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


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
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
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
