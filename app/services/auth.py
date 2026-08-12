"""Authentication + tenant onboarding.

Token scheme (see README, "Auth"):
  * access token  — stateless HS256 JWT, short TTL, carries user/company/role
  * refresh token — opaque 256-bit random, stored only as SHA-256 in
                    `user_sessions`, rotated on every use with reuse detection

Session/database discipline mirrors the rule already documented in
`app/db/tenant.py` and implemented by `public_tokens`:

    the SERVICE role (BYPASSRLS) performs ONLY the read-only global resolution
    that precedes knowing the tenant — email -> company, refresh-token-hash ->
    company. Every write then happens on the APP role inside tenant_context so
    RLS is exercised.

That keeps exactly one cross-tenant surface (a lookup that returns no tenant
data beyond the resolved ids) instead of letting auth run wholesale as a
privileged role.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    InvalidToken as InvalidJwt,
)
from app.core.security import (
    create_access_token,
    create_mfa_pre_auth_token,
    decode_mfa_pre_auth_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    password_needs_rehash,
    verify_password,
)
from app.core.token_denylist import bump_user_access_epoch, denylist_token
from app.db.models import UserRole
from app.db.tenant import tenant_context
from app.services import outbox, public_tokens
from app.services.outbox import enqueue

MAX_SLUG_LENGTH = 50
SLUG_ATTEMPTS = 5


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentials(AuthError):
    """Email/password rejected. Deliberately indistinguishable from unknown email."""


class AccountLocked(AuthError):
    """Too many consecutive failed logins. Maps to 423 (see app/api/errors.py).

    The message deliberately says nothing about remaining attempts or
    whether the account exists, so this cannot be used as a side channel to
    enumerate accounts or time-guess the lockout threshold.
    """


class InvalidRefreshToken(AuthError):
    """Refresh token unknown, expired, revoked, or already rotated."""


class MfaRequired(AuthError):
    """Password verified, but this account has MFA active (Phase 16).

    Carries the pre-auth token the caller must present to `POST
    /auth/login/mfa` together with a TOTP/backup code -- raised INSTEAD of
    `login` returning real tokens, so a caller cannot accidentally skip the
    second factor by ignoring a response field.
    """

    def __init__(self, pre_auth_token: str) -> None:
        super().__init__("MFA verification required")
        self.pre_auth_token = pre_auth_token


class MfaEnrollmentRequired(AuthError):
    """Password verified, but the company requires MFA (Phase 17, Area C.2)
    and this user has not enrolled it yet.

    Deliberately distinct from `MfaRequired`: that one means "prove your
    second factor right now" (the user already has MFA active and a
    pre-auth token lets them do so immediately). This one means "you must
    go enroll MFA before you can log in at all" -- there is no pre-auth
    token because there is no second factor to verify yet. The caller
    should be routed to the MFA enrollment flow (`POST /users/me/mfa`)
    using some other already-authenticated channel, or contact an admin;
    this deliberately does not itself grant any session so a
    company-wide MFA mandate cannot be silently bypassed by an unenrolled
    user just logging in as normal.
    """


class InvalidMfaPreAuthToken(AuthError):
    """Pre-auth token missing, malformed, expired, or of the wrong type."""


class InvalidResetToken(AuthError):
    """Password-reset token unknown, expired, or already used."""


class EmailAlreadyRegistered(AuthError):
    pass


class CompanySlugTaken(AuthError):
    pass


class RoleNotPermitted(AuthError):
    """Actor's role may not grant the requested role."""


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    session_id: uuid.UUID


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID
    company_id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:MAX_SLUG_LENGTH]
    return slug.strip("-") or "company"


def _available_slug(service_db: Session, base: str) -> str:
    """Pick a free company slug.

    The slug namespace is platform-global, so — like email — it can only be
    checked with the service role. The UNIQUE constraint remains the real
    guard; this loop just avoids failing signup on a common name.
    """
    candidate = base
    for _ in range(SLUG_ATTEMPTS):
        taken = service_db.execute(
            text("SELECT 1 FROM companies WHERE slug = :slug"), {"slug": candidate}
        ).first()
        if taken is None:
            return candidate
        suffix = secrets.token_hex(3)
        candidate = f"{base[: MAX_SLUG_LENGTH - len(suffix) - 1]}-{suffix}"
    return candidate


def _audit(
    db: Session,
    company_id: uuid.UUID,
    action: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit row. Caller must already hold tenant_context and commit."""
    db.execute(
        text(
            """
            INSERT INTO audit_log
                (company_id, actor_user_id, actor_ip, action,
                 resource_type, resource_id, metadata)
            VALUES (:cid, :actor, CAST(:ip AS inet), :action,
                    :rt, :rid, CAST(:meta AS jsonb))
            """
        ),
        {
            "cid": company_id,
            "actor": actor_user_id,
            "ip": ip,
            "action": action,
            "rt": resource_type,
            "rid": resource_id,
            "meta": json.dumps(metadata or {}),
        },
    )


def _issue_session(
    app_db: Session,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    family_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedTokens:
    """Insert a refresh-token row and mint the matching access token.

    Does NOT commit — the caller decides the transaction boundary so a session
    is never issued for a login that later fails.
    """
    raw_refresh, refresh_hash = new_opaque_token()
    session_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_ttl_days
    )

    with tenant_context(app_db, company_id):
        app_db.execute(
            text(
                """
                INSERT INTO user_sessions
                    (id, company_id, user_id, family_id, refresh_token_hash,
                     expires_at, user_agent, ip)
                VALUES (:sid, :cid, :uid, :fid, :hash,
                        :exp, :ua, CAST(:ip AS inet))
                """
            ),
            {
                "sid": session_id,
                "cid": company_id,
                "uid": user_id,
                "fid": family_id or session_id,
                "hash": refresh_hash,
                "exp": expires_at,
                "ua": user_agent,
                "ip": ip,
            },
        )

    return IssuedTokens(
        access_token=create_access_token(user_id, company_id, role, session_id),
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
        session_id=session_id,
    )


def _revoke_family(
    app_db: Session, company_id: uuid.UUID, family_id: uuid.UUID, reason: str
) -> int:
    """Revoke every live refresh token in a session family. Returns rows affected."""
    with tenant_context(app_db, company_id):
        rows = app_db.execute(
            text(
                """
                UPDATE user_sessions
                   SET revoked_at = now(), revoked_reason = :reason
                 WHERE company_id = :cid
                   AND family_id = :fid
                   AND revoked_at IS NULL
                RETURNING id
                """
            ),
            {"reason": reason, "cid": company_id, "fid": family_id},
        ).all()
    return len(rows)


def _revoke_all_user_sessions(
    app_db: Session, company_id: uuid.UUID, user_id: uuid.UUID, reason: str
) -> int:
    with tenant_context(app_db, company_id):
        rows = app_db.execute(
            text(
                """
                UPDATE user_sessions
                   SET revoked_at = now(), revoked_reason = :reason
                 WHERE company_id = :cid
                   AND user_id = :uid
                   AND revoked_at IS NULL
                RETURNING id
                """
            ),
            {"reason": reason, "cid": company_id, "uid": user_id},
        ).all()
    return len(rows)


def _to_authenticated_user(row) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=row.id,
        company_id=row.company_id,
        email=row.email,
        full_name=row.full_name,
        role=row.role,
        is_active=row.is_active,
    )


def _resolve_user_by_email(service_db: Session, email: str):
    """Global email -> user resolution. Service role only; read-only."""
    return service_db.execute(
        text(
            """
            SELECT id, company_id, password_hash, role, is_active,
                   failed_login_attempts, locked_until
              FROM users
             WHERE email = :email
            """
        ),
        {"email": email},
    ).first()


# ---------------------------------------------------------------------------
# onboarding
# ---------------------------------------------------------------------------
def signup(
    app_db: Session,
    service_db: Session,
    *,
    company_name: str,
    email: str,
    password: str,
    full_name: str | None = None,
    company_slug: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthenticatedUser, IssuedTokens]:
    """Create a new tenant and its first owner user, then log them in.

    The company UUID is generated here so tenant_context can be set BEFORE the
    INSERT — `companies` is RLS-protected, so its WITH CHECK requires
    app.current_company_id to already equal the new id.
    """
    email = normalize_email(email)
    password_hash = hash_password(password)  # raises WeakPassword

    explicit_slug = company_slug is not None
    base_slug = slugify(company_slug or company_name)
    slug = base_slug if explicit_slug else _available_slug(service_db, base_slug)

    company_id = uuid.uuid4()
    try:
        with tenant_context(app_db, company_id):
            app_db.execute(
                text(
                    """
                    INSERT INTO companies (id, slug, name)
                    VALUES (:cid, :slug, :name)
                    """
                ),
                {"cid": company_id, "slug": slug, "name": company_name.strip()},
            )
            user_id = app_db.execute(
                text(
                    """
                    INSERT INTO users
                        (company_id, email, password_hash, full_name, role)
                    VALUES (:cid, :email, :hash, :name, 'owner')
                    RETURNING id
                    """
                ),
                {
                    "cid": company_id,
                    "email": email,
                    "hash": password_hash,
                    "name": full_name,
                },
            ).scalar_one()

            tokens = _issue_session(
                app_db,
                company_id=company_id,
                user_id=user_id,
                role=UserRole.OWNER.value,
                ip=ip,
                user_agent=user_agent,
            )
            _audit(
                app_db,
                company_id,
                "company.signup",
                actor_user_id=user_id,
                resource_type="company",
                resource_id=company_id,
                ip=ip,
                metadata={"slug": slug, "email": email},
            )
            app_db.commit()
    except IntegrityError as exc:
        app_db.rollback()
        mapped = _map_integrity_error(exc)
        if mapped is None:
            raise
        raise mapped from exc

    user = AuthenticatedUser(
        id=user_id,
        company_id=company_id,
        email=email,
        full_name=full_name,
        role=UserRole.OWNER.value,
        is_active=True,
    )
    return user, tokens


def _map_integrity_error(exc: IntegrityError) -> AuthError | None:
    """Translate a unique-violation into a domain error, or None if unrecognised."""
    detail = str(exc.orig)
    if "uq_users_email_global" in detail or "users_company_id_email_key" in detail:
        return EmailAlreadyRegistered("email is already registered")
    if "companies_slug_key" in detail:
        return CompanySlugTaken("company slug is already taken")
    return None


# ---------------------------------------------------------------------------
# login / refresh / logout
# ---------------------------------------------------------------------------
def _lock_user_row_for_login(app_db: Session, company_id: uuid.UUID, user_id: uuid.UUID):
    """Re-read the user row FOR UPDATE inside tenant_context, for the login
    transaction's lockout bookkeeping. Must be called from inside an already-
    open `tenant_context(app_db, company_id)` block.

    Also joins `companies.mfa_required` (Phase 17, Area C.2) -- the login
    flow needs both "does THIS user have MFA enabled" and "does the
    company mandate MFA for everyone" in the same row to decide which of
    `MfaRequired` / `MfaEnrollmentRequired` (if either) to raise.
    """
    return app_db.execute(
        text(
            """
            SELECT u.id, u.password_hash, u.role, u.is_active,
                   u.failed_login_attempts, u.locked_until, u.mfa_enabled_at,
                   c.mfa_required AS company_mfa_required
              FROM users u
              JOIN companies c ON c.id = u.company_id
             WHERE u.id = :uid
             FOR UPDATE OF u
            """
        ),
        {"uid": user_id},
    ).first()


def login(
    app_db: Session,
    service_db: Session,
    *,
    email: str,
    password: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthenticatedUser, IssuedTokens]:
    """Verify credentials and issue a token pair.

    Every failure path raises the same InvalidCredentials so callers cannot
    distinguish unknown email / wrong password / deactivated account, EXCEPT
    the distinct `AccountLocked` raised once too many consecutive failures
    have accumulated (see module docstring on `AccountLocked` for why that
    one case is allowed to differ: it maps to 423 instead of 401, but its
    message still reveals nothing about remaining attempts or account
    existence).

    Lockout bookkeeping (`failed_login_attempts` / `locked_until`) is mutated
    under a `SELECT ... FOR UPDATE` on the user row taken inside THIS same
    transaction — never a separate round-trip — so concurrent login attempts
    against the same account serialize on that row lock instead of racing.
    """
    email = normalize_email(email)
    row = _resolve_user_by_email(service_db, email)

    if row is None:
        # Burn an equivalent hash verification so timing does not reveal
        # whether the address exists.
        verify_password(password, None)
        raise InvalidCredentials("invalid email or password")

    with tenant_context(app_db, row.company_id):
        locked_row = _lock_user_row_for_login(app_db, row.company_id, row.id)

        now = datetime.now(timezone.utc)
        currently_locked = (
            locked_row.locked_until is not None and locked_row.locked_until > now
        )

        if currently_locked:
            # Rejected even with the correct password: the whole point of a
            # lockout is that it does not matter whether this attempt's
            # password was right. No attempt-count/enumeration side channel.
            app_db.commit()
            raise AccountLocked("too many attempts, try again later")

        password_ok = verify_password(password, locked_row.password_hash)
        if not password_ok or not locked_row.is_active:
            new_attempts = locked_row.failed_login_attempts + 1
            new_locked_until = None
            if new_attempts >= settings.login_max_failed_attempts:
                new_locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            app_db.execute(
                text(
                    """
                    UPDATE users
                       SET failed_login_attempts = :attempts,
                           locked_until = :locked_until
                     WHERE id = :uid
                    """
                ),
                {
                    "attempts": new_attempts,
                    "locked_until": new_locked_until,
                    "uid": row.id,
                },
            )
            _audit(
                app_db,
                row.company_id,
                "user.login_failed",
                actor_user_id=row.id,
                resource_type="user",
                resource_id=row.id,
                ip=ip,
                metadata={
                    "reason": "inactive" if locked_row.is_active is False else "bad_password",
                    "failed_login_attempts": new_attempts,
                    "locked": new_locked_until is not None,
                },
            )
            app_db.commit()
            raise InvalidCredentials("invalid email or password")

        # Success: clear lockout state, upgrade the hash if needed, log in.
        app_db.execute(
            text(
                """
                UPDATE users
                   SET failed_login_attempts = 0,
                       locked_until = NULL,
                       last_login_at = now()
                 WHERE id = :uid
                """
            ),
            {"uid": row.id},
        )
        # Transparently upgrade the hash if the Argon2 cost parameters changed.
        if password_needs_rehash(locked_row.password_hash):
            app_db.execute(
                text("UPDATE users SET password_hash = :hash WHERE id = :uid"),
                {"hash": hash_password(password), "uid": row.id},
            )
        if locked_row.mfa_enabled_at is not None:
            # MFA active: this password check succeeded, but no real tokens
            # are issued yet. A short-lived pre-auth token is returned via
            # MfaRequired instead -- see app/api/v1/routes/auth.py's
            # POST /auth/login/mfa, which is the only place real tokens get
            # issued from here. No `user_sessions` row exists yet for this
            # attempt (`_issue_session` has not been called), so a login
            # that stops here for good leaves nothing behind to revoke.
            _audit(
                app_db,
                row.company_id,
                "user.login_mfa_required",
                actor_user_id=row.id,
                resource_type="user",
                resource_id=row.id,
                ip=ip,
            )
            app_db.commit()
            raise MfaRequired(create_mfa_pre_auth_token(row.id, row.company_id))

        if locked_row.company_mfa_required:
            # Company-wide MFA mandate (Phase 17, Area C.2), and this user
            # has not enrolled MFA (the branch above already handled the
            # "has MFA" case). No tokens, no pre-auth token either -- there
            # is no second factor to verify yet, only an enrollment gap to
            # close. See `MfaEnrollmentRequired`'s docstring for the full
            # rationale for why this is distinct from `MfaRequired`.
            _audit(
                app_db,
                row.company_id,
                "user.login_mfa_enrollment_required",
                actor_user_id=row.id,
                resource_type="user",
                resource_id=row.id,
                ip=ip,
            )
            app_db.commit()
            raise MfaEnrollmentRequired(
                "this company requires MFA; enroll it before logging in"
            )

        user = _to_authenticated_user(_load_user_row(app_db, row.id))
        tokens = _issue_session(
            app_db,
            company_id=row.company_id,
            user_id=row.id,
            role=locked_row.role,
            ip=ip,
            user_agent=user_agent,
        )
        _audit(
            app_db,
            row.company_id,
            "user.login",
            actor_user_id=row.id,
            resource_type="user",
            resource_id=row.id,
            ip=ip,
        )
        app_db.commit()

    return user, tokens


def login_mfa(
    app_db: Session,
    *,
    pre_auth_token: str,
    code: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthenticatedUser, IssuedTokens]:
    """Second step of an MFA login: exchange a pre-auth token + code for real tokens.

    `code` may be either a live TOTP code or an unused backup code -- see
    `app/services/mfa.py::verify_second_factor`, which tries TOTP first and
    only falls back to the backup-code table if that fails. Raises
    `InvalidMfaPreAuthToken` for an invalid/expired/wrong-type token (mapped
    to 401 by the route layer, same as any other login failure) and
    `app.services.mfa.InvalidMfaCode` for a wrong code.
    """
    from app.services import mfa as mfa_service

    try:
        claims = decode_mfa_pre_auth_token(pre_auth_token)
    except InvalidJwt as exc:
        raise InvalidMfaPreAuthToken(str(exc)) from exc

    mfa_service.verify_second_factor(
        app_db, company_id=claims.company_id, user_id=claims.user_id, code=code
    )

    with tenant_context(app_db, claims.company_id):
        user_row = _load_user_row(app_db, claims.user_id)
        if user_row is None or not user_row.is_active:
            raise InvalidCredentials("account is not active")

        user = _to_authenticated_user(user_row)
        tokens = _issue_session(
            app_db,
            company_id=claims.company_id,
            user_id=user.id,
            role=user.role,
            ip=ip,
            user_agent=user_agent,
        )
        _audit(
            app_db,
            claims.company_id,
            "user.login_mfa_verified",
            actor_user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            ip=ip,
        )
        app_db.commit()

    return user, tokens


def refresh(
    app_db: Session,
    service_db: Session,
    *,
    raw_refresh_token: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthenticatedUser, IssuedTokens]:
    """Rotate a refresh token.

    Rotation is a single conditional UPDATE, so concurrent use of the same
    token yields exactly one new pair. Presenting a token that was ALREADY
    rotated means the token leaked after use, so the whole family is revoked.
    """
    token_hash = hash_opaque_token(raw_refresh_token)

    row = service_db.execute(
        text(
            """
            SELECT id, company_id, user_id, family_id,
                   expires_at, rotated_at, revoked_at
              FROM user_sessions
             WHERE refresh_token_hash = :hash
            """
        ),
        {"hash": token_hash},
    ).first()

    if row is None:
        raise InvalidRefreshToken("refresh token not recognised")

    if row.rotated_at is not None:
        revoked = _revoke_family(app_db, row.company_id, row.family_id, "reuse_detected")
        with tenant_context(app_db, row.company_id):
            _audit(
                app_db,
                row.company_id,
                "auth.refresh_reuse_detected",
                actor_user_id=row.user_id,
                resource_type="user_session",
                resource_id=row.id,
                ip=ip,
                metadata={"revoked_sessions": revoked},
            )
            app_db.commit()
        raise InvalidRefreshToken("refresh token already used")

    if row.revoked_at is not None or row.expires_at <= datetime.now(timezone.utc):
        raise InvalidRefreshToken("refresh token expired or revoked")

    with tenant_context(app_db, row.company_id):
        rotated = app_db.execute(
            text(
                """
                UPDATE user_sessions
                   SET rotated_at = now()
                 WHERE id = :sid
                   AND rotated_at IS NULL
                   AND revoked_at IS NULL
                   AND expires_at > now()
                RETURNING family_id, user_id
                """
            ),
            {"sid": row.id},
        ).first()
        if rotated is None:
            # Lost a race with a concurrent refresh, or the row was revoked
            # between the lookup and here. Not treated as theft.
            app_db.rollback()
            raise InvalidRefreshToken("refresh token no longer valid")

        user_row = _load_user_row(app_db, rotated.user_id)
        if user_row is None or not user_row.is_active:
            # Discard the rotation; the family dies instead.
            app_db.rollback()
            _revoke_family(app_db, row.company_id, row.family_id, "user_inactive")
            app_db.commit()
            raise InvalidRefreshToken("account is not active")

        user = _to_authenticated_user(user_row)
        tokens = _issue_session(
            app_db,
            company_id=row.company_id,
            user_id=user.id,
            role=user.role,
            family_id=rotated.family_id,
            ip=ip,
            user_agent=user_agent,
        )
        _audit(
            app_db,
            row.company_id,
            "auth.refreshed",
            actor_user_id=user.id,
            resource_type="user_session",
            resource_id=tokens.session_id,
            ip=ip,
        )
        app_db.commit()

    return user, tokens


def logout(
    app_db: Session,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    all_devices: bool = False,
    access_token_jti: str | None = None,
    access_token_expires_at: datetime | None = None,
) -> int:
    """Revoke refresh tokens, and denylist the caller's current access token.

    By default the caller's session family is revoked (this device). Refresh
    token revocation alone does not stop an already-issued access token from
    working -- it is a stateless JWT valid until its own `exp`. Passing
    `access_token_jti`/`access_token_expires_at` (the claims of the token
    used to authenticate THIS logout call) additionally adds it to the Redis
    JTI denylist (`app.core.token_denylist`) so it stops working immediately
    rather than lingering for up to `access_token_ttl_minutes`. Both
    parameters are optional so internal/service callers that revoke
    sessions without an access token in hand (e.g. an admin force-logout of
    another user) still work -- they simply do not get the immediate-
    revocation guarantee for a token they never had.

    When `all_devices=True`, a per-user access-token cutoff is also written
    so OTHER devices' still-valid access tokens (whose jtis this handler
    does not know) stop working immediately rather than lingering until
    their natural `exp` — marine threat model Scenario 1 (lost/stolen
    device), 2026-08-11.
    """
    if access_token_jti is not None and access_token_expires_at is not None:
        denylist_token(access_token_jti, access_token_expires_at)

    if all_devices:
        revoked = _revoke_all_user_sessions(app_db, company_id, user_id, "logout_all")
        # Bump the per-user access epoch so EVERY outstanding access token
        # (not just the caller's jti) fails the next deps check. New logins
        # stamp the new epoch and work immediately.
        bump_user_access_epoch(user_id)
    else:
        with tenant_context(app_db, company_id):
            family_id = app_db.execute(
                text("SELECT family_id FROM user_sessions WHERE id = :sid"),
                {"sid": session_id},
            ).scalar()
        revoked = (
            _revoke_family(app_db, company_id, family_id, "logout")
            if family_id is not None
            else 0
        )

    with tenant_context(app_db, company_id):
        _audit(
            app_db,
            company_id,
            "user.logout",
            actor_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            metadata={"all_devices": all_devices, "revoked_sessions": revoked},
        )
        app_db.commit()
    return revoked


# ---------------------------------------------------------------------------
# user records
# ---------------------------------------------------------------------------
def _load_user_row(app_db: Session, user_id: uuid.UUID):
    """Read a user inside the caller's existing tenant_context (RLS applies)."""
    return app_db.execute(
        text(
            """
            SELECT id, company_id, email, full_name, role, is_active
              FROM users
             WHERE id = :uid
            """
        ),
        {"uid": user_id},
    ).first()


def load_user(
    app_db: Session, company_id: uuid.UUID, user_id: uuid.UUID
) -> AuthenticatedUser | None:
    """Load a user scoped to `company_id`. Returns None if RLS hides it."""
    with tenant_context(app_db, company_id):
        row = _load_user_row(app_db, user_id)
    return _to_authenticated_user(row) if row is not None else None


def create_user(
    app_db: Session,
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str,
    email: str,
    password: str,
    role: str,
    full_name: str | None = None,
    ip: str | None = None,
) -> AuthenticatedUser:
    """Invite (provision) a user into the actor's company.

    Only owners may create other owners — otherwise an admin could escalate
    itself to full billing control.
    """
    if role == UserRole.OWNER.value and actor_role != UserRole.OWNER.value:
        raise RoleNotPermitted("only an owner can create another owner")

    email = normalize_email(email)
    password_hash = hash_password(password)

    try:
        with tenant_context(app_db, company_id):
            user_id = app_db.execute(
                text(
                    """
                    INSERT INTO users
                        (company_id, email, password_hash, full_name, role)
                    VALUES (:cid, :email, :hash, :name, CAST(:role AS user_role))
                    RETURNING id
                    """
                ),
                {
                    "cid": company_id,
                    "email": email,
                    "hash": password_hash,
                    "name": full_name,
                    "role": role,
                },
            ).scalar_one()
            _audit(
                app_db,
                company_id,
                "user.invited",
                actor_user_id=actor_user_id,
                resource_type="user",
                resource_id=user_id,
                ip=ip,
                metadata={"email": email, "role": role},
            )
            app_db.commit()
    except IntegrityError as exc:
        app_db.rollback()
        mapped = _map_integrity_error(exc)
        if mapped is None:
            raise
        raise mapped from exc

    return AuthenticatedUser(
        id=user_id,
        company_id=company_id,
        email=email,
        full_name=full_name,
        role=role,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# invite-link user provisioning
# ---------------------------------------------------------------------------
#: An invite's raison d'etre is to create exactly one account; once accepted
#: there is nothing left for the token to authorize, so it is single-use.
INVITE_TOKEN_MAX_USES = 1


class InviteNotFound(AuthError):
    """Invite token unknown, expired, revoked, wrong purpose, or already used."""


def create_invite(
    app_db: Session,
    service_db: Session,
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str,
    email: str,
    role: str,
    full_name: str | None = None,
    ip: str | None = None,
) -> dict[str, Any]:
    """Issue an invite-link for a not-yet-existing user in the actor's company.

    Mirrors `create_user`'s role-escalation guard exactly (an admin still
    cannot invite an owner) and its email-uniqueness guard (checked globally,
    same as signup/create_user, since email identifies exactly one account
    platform-wide).

    The invite reuses the existing `public_tokens` machinery (see migration
    0005 / README) instead of a parallel table. `public_tokens.resource_id`
    is `UUID NOT NULL`, and the invited user does not exist yet, so — exactly
    like `signup` pre-generates `company_id` before the `companies` INSERT —
    this pre-generates the future user's id and carries it in the token's
    `resource_id`. `accept_invite` uses that same id as the new user's
    primary key, so the token and the eventual row are linked from creation.
    """
    if role == UserRole.OWNER.value and actor_role != UserRole.OWNER.value:
        raise RoleNotPermitted("only an owner can invite another owner")

    email = normalize_email(email)

    # Global uniqueness check, same rule signup/create_user rely on the
    # UNIQUE index for; checked explicitly here too so a duplicate invite
    # produces a clean 409 rather than deferring to a later accept-time
    # IntegrityError once a password has already been collected from the
    # invitee.
    existing = _resolve_user_by_email(service_db, email)
    service_db.commit()
    if existing is not None:
        raise EmailAlreadyRegistered("email is already registered")

    with tenant_context(app_db, company_id):
        company_row = app_db.execute(
            text("SELECT name FROM companies WHERE id = :cid"), {"cid": company_id}
        ).first()
        inviter_row = app_db.execute(
            text("SELECT full_name, email FROM users WHERE id = :uid"),
            {"uid": actor_user_id},
        ).first()

    company_name = company_row.name if company_row else "HarborIQ"
    inviter_name = (inviter_row.full_name or inviter_row.email) if inviter_row else None

    invited_user_id = uuid.uuid4()
    raw_token = public_tokens.issue_public_token(
        app_db,
        company_id,
        "user_invite",
        invited_user_id,
        "user_invite",
        ttl_hours=settings.invite_ttl_hours,
        max_uses=INVITE_TOKEN_MAX_USES,
    )
    accept_url = f"{settings.app_base_url.rstrip('/')}/accept-invite/{raw_token}"

    with tenant_context(app_db, company_id):
        outbox.enqueue(
            app_db,
            company_id,
            "user_invite.sent",
            {
                "email": email,
                "role": role,
                "full_name": full_name,
                "company_name": company_name,
                "inviter_name": inviter_name,
                "invite_token": raw_token,
                "ttl_hours": settings.invite_ttl_hours,
            },
        )
        _audit(
            app_db,
            company_id,
            "user.invited",
            actor_user_id=actor_user_id,
            resource_type="user_invite",
            resource_id=invited_user_id,
            ip=ip,
            metadata={"email": email, "role": role},
        )
        app_db.commit()

    return {
        "email": email,
        "role": role,
        "full_name": full_name,
        "company_name": company_name,
        "expires_in_hours": settings.invite_ttl_hours,
        "accept_url": accept_url,
    }


def _validate_invite_row(row) -> None:
    """Shared purpose/expiry/revocation/use-limit checks for an invite row."""
    if row is None:
        raise InviteNotFound("invite not found")
    if row.purpose != "user_invite" or row.resource_type != "user_invite":
        raise InviteNotFound("invite not found")
    if row.revoked_at is not None:
        raise InviteNotFound("invite has been revoked")
    if row.expires_at <= datetime.now(timezone.utc):
        raise InviteNotFound("invite has expired")
    if row.uses >= row.max_uses:
        raise InviteNotFound("invite has already been used")


def _resolve_invite_token(service_db: Session, raw_token: str):
    """Service-role, non-locking lookup of a live `user_invite` public token.

    Read-only: used to discover which tenant a token belongs to (needed
    before a `tenant_context` can even be opened) and for the read-only
    preview endpoint. `accept_invite` does NOT hold this lock across
    sessions — it re-resolves and locks the row on `app_db`, inside the
    tenant's own `tenant_context`, in the same transaction it consumes the
    token in. Locking here on `service_db` and consuming on a different
    session/connection would hold the row lock for the lifetime of the
    request instead of just the consuming transaction, and would deadlock
    against that second session trying to acquire the same lock.
    """
    token_hash = public_tokens._hash(raw_token)
    row = service_db.execute(
        text(
            """
            SELECT id, company_id, resource_type, resource_id, purpose,
                   expires_at, max_uses, uses, revoked_at
              FROM public_tokens
             WHERE token_hash = :th
            """
        ),
        {"th": token_hash},
    ).first()
    service_db.commit()  # read-only; releases immediately rather than idling
    _validate_invite_row(row)
    return row


def get_invite(service_db: Session, raw_token: str) -> dict[str, Any]:
    """Read-only preview for the accept-invite page: email/role/company name.

    Does NOT consume a use — a candidate may load this page, reconsider,
    reload it, etc. before ever submitting a password; only `accept_invite`
    burns the token.
    """
    row = _resolve_invite_token(service_db, raw_token)
    outbox_row = service_db.execute(
        text(
            """
            SELECT payload FROM outbox_events
             WHERE company_id = :cid AND event_type = 'user_invite.sent'
               AND payload->>'invite_token' = :token
             ORDER BY id DESC LIMIT 1
            """
        ),
        {"cid": row.company_id, "token": raw_token},
    ).first()
    company_row = service_db.execute(
        text("SELECT name FROM companies WHERE id = :cid"), {"cid": row.company_id}
    ).first()
    service_db.commit()

    payload = outbox_row.payload if outbox_row else {}
    return {
        "email": payload.get("email", ""),
        "role": payload.get("role", ""),
        "full_name": payload.get("full_name"),
        "company_name": (company_row.name if company_row else payload.get("company_name", "")),
    }


def accept_invite(
    app_db: Session,
    service_db: Session,
    *,
    raw_token: str,
    password: str,
    full_name: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthenticatedUser, IssuedTokens]:
    """Consume an invite token, create the user, and log them straight in.

    Reuses the exact password-strength + hashing path `create_user`/`signup`
    already use (`hash_password`, which calls `validate_password_strength`)
    rather than duplicating divergent logic.
    """
    # First pass: a non-locking lookup on the service role just to learn
    # which tenant this token belongs to (needed before `tenant_context` can
    # be opened at all) and to fail fast on an obviously-dead token.
    precheck_row = _resolve_invite_token(service_db, raw_token)
    company_id = precheck_row.company_id
    token_hash = public_tokens._hash(raw_token)

    outbox_row = service_db.execute(
        text(
            """
            SELECT payload FROM outbox_events
             WHERE company_id = :cid AND event_type = 'user_invite.sent'
               AND payload->>'invite_token' = :token
             ORDER BY id DESC LIMIT 1
            """
        ),
        {"cid": company_id, "token": raw_token},
    ).first()
    service_db.commit()
    if outbox_row is None:
        raise InviteNotFound("invite not found")
    payload = outbox_row.payload

    email = normalize_email(payload["email"])
    role = payload["role"]
    invited_full_name = full_name or payload.get("full_name")
    password_hash = hash_password(password)  # raises WeakPassword

    try:
        with tenant_context(app_db, company_id):
            # Second pass, inside the SAME transaction that consumes the
            # token and inserts the user: re-lock and re-validate on
            # `app_db` so the lock and the mutation it protects are never
            # split across two different DB sessions.
            locked_row = app_db.execute(
                text(
                    """
                    SELECT id, resource_id, resource_type, purpose,
                           expires_at, max_uses, uses, revoked_at
                      FROM public_tokens
                     WHERE token_hash = :th
                       FOR UPDATE
                    """
                ),
                {"th": token_hash},
            ).first()
            _validate_invite_row(locked_row)
            user_id = locked_row.resource_id

            app_db.execute(
                text(
                    """
                    INSERT INTO users
                        (id, company_id, email, password_hash, full_name, role)
                    VALUES (:uid, :cid, :email, :hash, :name, CAST(:role AS user_role))
                    """
                ),
                {
                    "uid": user_id,
                    "cid": company_id,
                    "email": email,
                    "hash": password_hash,
                    "name": invited_full_name,
                    "role": role,
                },
            )

            consumed = app_db.execute(
                text(
                    """
                    UPDATE public_tokens
                       SET uses = uses + 1
                     WHERE id = :id AND uses < max_uses
                    RETURNING id
                    """
                ),
                {"id": locked_row.id},
            ).first()
            if consumed is None:
                app_db.rollback()
                raise InviteNotFound("invite has already been used")

            _audit(
                app_db,
                company_id,
                "user.invite_accepted",
                actor_user_id=user_id,
                resource_type="user",
                resource_id=user_id,
                ip=ip,
                metadata={"email": email, "role": role},
            )

            tokens = _issue_session(
                app_db,
                company_id=company_id,
                user_id=user_id,
                role=role,
                ip=ip,
                user_agent=user_agent,
            )
            app_db.commit()
    except IntegrityError as exc:
        app_db.rollback()
        mapped = _map_integrity_error(exc)
        if mapped is None:
            raise
        raise mapped from exc

    user = AuthenticatedUser(
        id=user_id,
        company_id=company_id,
        email=email,
        full_name=invited_full_name,
        role=role,
        is_active=True,
    )
    return user, tokens


# ---------------------------------------------------------------------------
# password reset
# ---------------------------------------------------------------------------
def request_password_reset(
    app_db: Session,
    service_db: Session,
    *,
    email: str,
    ip: str | None = None,
) -> None:
    """Issue a single-use reset token and queue the delivery email.

    Silently returns for unknown addresses so the endpoint cannot be used to
    enumerate accounts. The raw token is never returned to the caller: it goes
    out through the outbox, which is the repo's mechanism for post-commit side
    effects.
    """
    email = normalize_email(email)
    row = _resolve_user_by_email(service_db, email)
    if row is None or not row.is_active:
        return

    raw_token, token_hash = new_opaque_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_ttl_minutes
    )

    with tenant_context(app_db, row.company_id):
        app_db.execute(
            text(
                """
                INSERT INTO password_reset_tokens
                    (company_id, user_id, token_hash, expires_at, requested_ip)
                VALUES (:cid, :uid, :hash, :exp, CAST(:ip AS inet))
                """
            ),
            {
                "cid": row.company_id,
                "uid": row.id,
                "hash": token_hash,
                "exp": expires_at,
                "ip": ip,
            },
        )
        _audit(
            app_db,
            row.company_id,
            "user.password_reset_requested",
            actor_user_id=row.id,
            resource_type="user",
            resource_id=row.id,
            ip=ip,
        )

    enqueue(
        app_db,
        row.company_id,
        "auth.password_reset_requested",
        {"email": email, "reset_token": raw_token, "expires_at": expires_at.isoformat()},
    )
    app_db.commit()


def confirm_password_reset(
    app_db: Session,
    service_db: Session,
    *,
    raw_token: str,
    new_password: str,
) -> None:
    """Consume a reset token, set the new password, and log out every session."""
    token_hash = hash_opaque_token(raw_token)
    # Validate the new password BEFORE burning the token, so a rejected
    # password does not force the user to request a second email.
    password_hash = hash_password(new_password)

    row = service_db.execute(
        text(
            """
            SELECT id, company_id, user_id, expires_at, used_at
              FROM password_reset_tokens
             WHERE token_hash = :hash
            """
        ),
        {"hash": token_hash},
    ).first()
    if row is None:
        raise InvalidResetToken("reset token not recognised")

    with tenant_context(app_db, row.company_id):
        consumed = app_db.execute(
            text(
                """
                UPDATE password_reset_tokens
                   SET used_at = now()
                 WHERE id = :tid
                   AND used_at IS NULL
                   AND expires_at > now()
                RETURNING user_id
                """
            ),
            {"tid": row.id},
        ).first()
        if consumed is None:
            app_db.rollback()
            raise InvalidResetToken("reset token expired or already used")

        app_db.execute(
            text("UPDATE users SET password_hash = :hash WHERE id = :uid"),
            {"hash": password_hash, "uid": consumed.user_id},
        )
        # Any other outstanding reset tokens for this user are now void.
        app_db.execute(
            text(
                """
                UPDATE password_reset_tokens
                   SET used_at = now()
                 WHERE user_id = :uid AND used_at IS NULL
                """
            ),
            {"uid": consumed.user_id},
        )
        _audit(
            app_db,
            row.company_id,
            "user.password_reset_completed",
            actor_user_id=consumed.user_id,
            resource_type="user",
            resource_id=consumed.user_id,
        )

    # A password change must invalidate every existing session.
    _revoke_all_user_sessions(app_db, row.company_id, consumed.user_id, "password_reset")
    app_db.commit()
