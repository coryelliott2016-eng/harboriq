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
