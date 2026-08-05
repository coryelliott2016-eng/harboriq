"""Authentication primitives: password hashing, access tokens, opaque tokens.

Password hashing uses Argon2id (argon2-cffi) with the library's current
defaults. Unlike bcrypt it has no silent 72-byte truncation, and the stored
hash embeds its own parameters so `needs_rehash` can upgrade cost factors on
the next successful login.

Access tokens are stateless HS256 JWTs. Refresh / password-reset tokens are
opaque 256-bit random strings stored only as SHA-256 digests — the same
hash-only model `public_tokens` already uses, so a database dump never yields
a usable credential.

Phase 16 adds a THIRD, narrower token type: the MFA pre-auth token (see
`create_mfa_pre_auth_token`/`decode_mfa_pre_auth_token`). It reuses this same
HS256/`jwt_secret` machinery (a fourth signing key/library would be pure
duplication for no security benefit) but is deliberately not an
`AccessClaims`/`typ="access"` token — it carries no `role`/`sid` (a
pre-auth token grants no API access at all, only "you already proved you
know this user's password, now prove the second factor") and has a much
shorter TTL than a real access token.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

TOKEN_BYTES = 32  # 256-bit entropy, matching public_tokens
MAX_PASSWORD_BYTES = 1024  # bound the work an unauthenticated caller can request

#: How long a `POST /auth/login`-issued MFA pre-auth token remains usable
#: against `POST /auth/login/mfa`. Short on purpose: it exists only to
#: bridge the gap between "password verified" and "second factor verified"
#: in the same login attempt, not to be a long-lived credential of its own.
MFA_PRE_AUTH_TOKEN_TTL_MINUTES = 5

_hasher = PasswordHasher()

# Verified against when an email does not resolve, so a caller cannot
# distinguish "unknown email" from "wrong password" by response time.
_DUMMY_HASH = _hasher.hash("harboriq-timing-equalizer")


class InvalidToken(Exception):
    """Access token missing, malformed, expired, or of the wrong type."""


class WeakPassword(Exception):
    """Password does not meet the configured policy."""


def validate_password_strength(password: str) -> None:
    if len(password) < settings.password_min_length:
        raise WeakPassword(
            f"password must be at least {settings.password_min_length} characters"
        )
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise WeakPassword("password is too long")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish-time password check.

    `password_hash` is None for users provisioned without a password (e.g. a
    future email-invite flow); those accounts must never authenticate, but we
    still burn a verification to keep the timing profile flat.
    """
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return False
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def hash_backup_code(code: str) -> str:
    """Hash an MFA backup code with the same Argon2id hasher as passwords.

    A backup code is functionally a one-time-use short password (see
    `app/services/mfa.py`), so it earns the same treatment `hash_password`
    already gives real passwords rather than a second bespoke scheme —
    deliberately does NOT go through `validate_password_strength` (backup
    codes are a fixed, server-generated shape, not user-chosen).
    """
    return _hasher.hash(code)


def verify_backup_code(code: str, code_hash: str) -> bool:
    try:
        _hasher.verify(code_hash, code)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    company_id: uuid.UUID
    role: str
    session_id: uuid.UUID
    jti: str
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, company_id: uuid.UUID, role: str, session_id: uuid.UUID
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(user_id),
        "cid": str(company_id),
        "role": role,
        "sid": str(session_id),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessClaims:
    """Verify signature, issuer, and expiry. Raises InvalidToken on any problem."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    if payload.get("typ") != "access":
        raise InvalidToken("not an access token")
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            company_id=uuid.UUID(payload["cid"]),
            role=payload["role"],
            session_id=uuid.UUID(payload["sid"]),
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidToken("malformed claims") from exc


@dataclass(frozen=True)
class MfaPreAuthClaims:
    user_id: uuid.UUID
    company_id: uuid.UUID


def create_mfa_pre_auth_token(user_id: uuid.UUID, company_id: uuid.UUID) -> str:
    """Issue a short-lived token proving "password already verified".

    Returned by `POST /auth/login` INSTEAD OF real tokens when the user has
    MFA active (see `app/services/auth.py::login`). Carries no `role`/`sid`
    claim and is never accepted by `get_current_principal` (a different
    `typ`, so `decode_access_token` rejects it outright) — it grants no API
    access, only the right to attempt `POST /auth/login/mfa` for THIS one
    user within `MFA_PRE_AUTH_TOKEN_TTL_MINUTES`.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(user_id),
        "cid": str(company_id),
        "typ": "mfa_pre_auth",
        "iat": now,
        "exp": now + timedelta(minutes=MFA_PRE_AUTH_TOKEN_TTL_MINUTES),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_mfa_pre_auth_token(token: str) -> MfaPreAuthClaims:
    """Verify signature, issuer, expiry, and `typ`. Raises InvalidToken on any problem."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    if payload.get("typ") != "mfa_pre_auth":
        raise InvalidToken("not an MFA pre-auth token")
    try:
        return MfaPreAuthClaims(
            user_id=uuid.UUID(payload["sub"]),
            company_id=uuid.UUID(payload["cid"]),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidToken("malformed claims") from exc


def new_opaque_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). The raw value is shown to the client once."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_opaque_token(raw)


def hash_opaque_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
