"""Authentication primitives: password hashing, access tokens, opaque tokens.

Password hashing uses Argon2id (argon2-cffi) with the library's current
defaults. Unlike bcrypt it has no silent 72-byte truncation, and the stored
hash embeds its own parameters so `needs_rehash` can upgrade cost factors on
the next successful login.

Access tokens are stateless HS256 JWTs. Refresh / password-reset tokens are
opaque 256-bit random strings stored only as SHA-256 digests — the same
hash-only model `public_tokens` already uses, so a database dump never yields
a usable credential.
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


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    company_id: uuid.UUID
    role: str
    session_id: uuid.UUID


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
            options={"require": ["exp", "iat", "sub", "iss"]},
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
        )
    except (KeyError, ValueError) as exc:
        raise InvalidToken("malformed claims") from exc


def new_opaque_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). The raw value is shown to the client once."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_opaque_token(raw)


def hash_opaque_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
