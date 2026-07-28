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
    create_access_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    password_needs_rehash,
    verify_password,
)
from app.db.models import UserRole
from app.db.tenant import tenant_context
from app.services.outbox import enqueue

MAX_SLUG_LENGTH = 50
SLUG_ATTEMPTS = 5


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentials(AuthError):
    """Email/password rejected. Deliberately indistinguishable from unknown email."""


class InvalidRefreshToken(AuthError):
    """Refresh token unknown, expired, revoked, or already rotated."""


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
            SELECT id, company_id, password_hash, role, is_active
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
    distinguish unknown email / wrong password / deactivated account.
    """
    email = normalize_email(email)
    row = _resolve_user_by_email(service_db, email)

    if row is None:
        # Burn an equivalent hash verification so timing does not reveal
        # whether the address exists.
        verify_password(password, None)
        raise InvalidCredentials("invalid email or password")

    if not verify_password(password, row.password_hash) or not row.is_active:
        with tenant_context(app_db, row.company_id):
            _audit(
                app_db,
                row.company_id,
                "user.login_failed",
                actor_user_id=row.id,
                resource_type="user",
                resource_id=row.id,
                ip=ip,
                metadata={"reason": "inactive" if row.is_active is False else "bad_password"},
            )
            app_db.commit()
        raise InvalidCredentials("invalid email or password")

    with tenant_context(app_db, row.company_id):
        # Transparently upgrade the hash if the Argon2 cost parameters changed.
        if password_needs_rehash(row.password_hash):
            app_db.execute(
                text("UPDATE users SET password_hash = :hash WHERE id = :uid"),
                {"hash": hash_password(password), "uid": row.id},
            )
        app_db.execute(
            text("UPDATE users SET last_login_at = now() WHERE id = :uid"),
            {"uid": row.id},
        )
        user = _to_authenticated_user(_load_user_row(app_db, row.id))
        tokens = _issue_session(
            app_db,
            company_id=row.company_id,
            user_id=row.id,
            role=row.role,
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
) -> int:
    """Revoke refresh tokens.

    By default the caller's session family is revoked (this device). The
    already-issued access token stays valid until it expires — that window is
    `access_token_ttl_minutes`.
    """
    if all_devices:
        revoked = _revoke_all_user_sessions(app_db, company_id, user_id, "logout_all")
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
