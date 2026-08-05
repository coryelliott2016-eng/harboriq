"""MFA / TOTP enrollment, confirmation, disable, and backup-code recovery
(Phase 16).

Flow:
    1. `POST /users/me/mfa/enroll` -- generates a fresh TOTP secret via
       `pyotp`, Fernet-encrypts it (`app/core/crypto.py`) and writes it to
       `users.mfa_secret_enc` UNCONFIRMED (`mfa_enabled_at` stays NULL).
       Returns the `otpauth://` URI (for QR rendering) and the raw base32
       secret (for manual entry) -- the ONLY time the raw secret is ever
       shown; it is encrypted at rest immediately after.
    2. `POST /users/me/mfa/confirm` -- verifies a live TOTP code against the
       pending secret. On success, sets `mfa_enabled_at` and generates a
       fresh batch of one-time backup codes (shown once, stored hashed).
    3. `POST /users/me/mfa/disable` -- requires the user's current password
       (re-entry, not just an existing session) and clears both
       `mfa_secret_enc` and `mfa_enabled_at`, plus every unused backup code.
    4. Login: `app/services/auth.py::login` checks `mfa_enabled_at`. If set,
       it returns an `MfaRequired` signal instead of real tokens; the route
       layer issues a pre-auth token (`app/core/security.py`) and the client
       must call `POST /auth/login/mfa` with that token plus a TOTP code OR
       an unused backup code to get real tokens.

Tenant/session discipline matches the rest of `app/services/auth.py`: every
write happens under `tenant_context` so RLS is exercised; nothing here uses
the service/BYPASSRLS role.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

import pyotp
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.crypto import InvalidToken as InvalidCiphertext
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.security import (
    hash_backup_code,
    verify_backup_code,
    verify_password,
)
from app.db.tenant import tenant_context

#: How many backup codes are issued per confirm/regenerate. Ten is the
#: common industry default (GitHub, Google) -- enough that a user who loses
#: a handful over time is not immediately locked out, few enough that
#: showing/printing them fits on one screen.
BACKUP_CODE_COUNT = 10
#: Human-typeable: uppercase letters + digits, hyphenated in the middle for
#: readability (e.g. "7K3F-9QXR"), no ambiguous 0/O or 1/I characters.
_BACKUP_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_BACKUP_CODE_HALF_LEN = 4

TOTP_ISSUER = "HarborIQ"


class MfaError(Exception):
    """Base class for MFA failures."""


class MfaAlreadyEnabled(MfaError):
    """Enroll called while MFA is already confirmed and active."""


class MfaNotPending(MfaError):
    """Confirm called with no pending (unconfirmed) enrollment to confirm."""


class MfaNotEnabled(MfaError):
    """Disable (or a login second-factor check) called with MFA not active."""


class InvalidMfaCode(MfaError):
    """TOTP code (or backup code) did not verify."""


class InvalidPassword(MfaError):
    """Password re-entry (required for disable) did not match."""


@dataclass(frozen=True)
class EnrollResult:
    otpauth_uri: str
    secret: str


def _generate_backup_codes() -> list[str]:
    return [
        "-".join(
            "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(_BACKUP_CODE_HALF_LEN))
            for _ in range(2)
        )
        for _ in range(BACKUP_CODE_COUNT)
    ]


def _load_mfa_row(app_db: Session, user_id: uuid.UUID):
    return app_db.execute(
        text(
            """
            SELECT id, password_hash, mfa_secret_enc, mfa_enabled_at
              FROM users
             WHERE id = :uid
             FOR UPDATE
            """
        ),
        {"uid": user_id},
    ).first()


def enroll(app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID) -> EnrollResult:
    """Start (or restart) MFA enrollment. Overwrites any prior pending secret.

    Deliberately allowed to be called again before `confirm` (e.g. the user's
    authenticator app timed out, or they want a fresh QR code) -- only a
    CONFIRMED enrollment (`mfa_enabled_at` set) blocks re-enrollment, since
    replacing an active secret without re-authenticating would let a
    hijacked session silently swap out the second factor.
    """
    with tenant_context(app_db, company_id):
        row = _load_mfa_row(app_db, user_id)
        if row is None:
            raise MfaNotEnabled("user not found")
        if row.mfa_enabled_at is not None:
            raise MfaAlreadyEnabled("MFA is already enabled; disable it before re-enrolling")

        secret = pyotp.random_base32()
        app_db.execute(
            text("UPDATE users SET mfa_secret_enc = :enc WHERE id = :uid"),
            {"enc": encrypt_secret(secret), "uid": user_id},
        )
        app_db.commit()

    return EnrollResult(
        otpauth_uri=pyotp.TOTP(secret).provisioning_uri(
            name=str(user_id), issuer_name=TOTP_ISSUER
        ),
        secret=secret,
    )


def confirm(
    app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID, code: str
) -> list[str]:
    """Verify a live TOTP code against the pending secret and activate MFA.

    Returns the batch of freshly-generated backup codes IN PLAINTEXT -- the
    only time they are ever available in that form; only their Argon2id
    hashes are persisted (see `app/core/security.py::hash_backup_code`).
    """
    with tenant_context(app_db, company_id):
        row = _load_mfa_row(app_db, user_id)
        if row is None:
            raise MfaNotEnabled("user not found")
        if row.mfa_enabled_at is not None:
            raise MfaAlreadyEnabled("MFA is already enabled")
        if row.mfa_secret_enc is None:
            raise MfaNotPending("no pending MFA enrollment; call enroll first")

        secret = decrypt_secret(row.mfa_secret_enc)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise InvalidMfaCode("invalid authentication code")

        app_db.execute(
            text("UPDATE users SET mfa_enabled_at = now() WHERE id = :uid"),
            {"uid": user_id},
        )
        # Replace any leftover codes from a prior enroll/disable cycle —
        # confirm always produces exactly one fresh, complete batch.
        app_db.execute(
            text("DELETE FROM mfa_backup_codes WHERE company_id = :cid AND user_id = :uid"),
            {"cid": company_id, "uid": user_id},
        )
        codes = _generate_backup_codes()
        for code_plain in codes:
            app_db.execute(
                text(
                    """
                    INSERT INTO mfa_backup_codes (company_id, user_id, code_hash)
                    VALUES (:cid, :uid, :hash)
                    """
                ),
                {"cid": company_id, "uid": user_id, "hash": hash_backup_code(code_plain)},
            )
        app_db.commit()

    return codes


def disable(
    app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID, password: str
) -> None:
    """Turn MFA off. Requires the caller's current password (not just a live session).

    A stolen/idle browser session should NOT be sufficient to strip a
    user's second factor -- that is exactly the privilege escalation MFA
    exists to prevent, so this re-checks the password the same way
    `confirm_password_reset`-adjacent flows never trust "already logged in"
    alone for a security-downgrading action.
    """
    with tenant_context(app_db, company_id):
        row = _load_mfa_row(app_db, user_id)
        if row is None:
            raise MfaNotEnabled("user not found")
        if not verify_password(password, row.password_hash):
            raise InvalidPassword("incorrect password")
        if row.mfa_enabled_at is None and row.mfa_secret_enc is None:
            raise MfaNotEnabled("MFA is not enabled")

        app_db.execute(
            text(
                """
                UPDATE users
                   SET mfa_secret_enc = NULL, mfa_enabled_at = NULL
                 WHERE id = :uid
                """
            ),
            {"uid": user_id},
        )
        app_db.execute(
            text("DELETE FROM mfa_backup_codes WHERE company_id = :cid AND user_id = :uid"),
            {"cid": company_id, "uid": user_id},
        )
        app_db.commit()


def is_mfa_active(app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    with tenant_context(app_db, company_id):
        row = app_db.execute(
            text("SELECT mfa_enabled_at FROM users WHERE id = :uid"), {"uid": user_id}
        ).first()
    return row is not None and row.mfa_enabled_at is not None


def verify_second_factor(
    app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID, code: str
) -> None:
    """Verify `code` as either a live TOTP code or an unused backup code.

    Backup codes are tried second (TOTP is the common case) and, on match,
    are atomically claimed (`WHERE used_at IS NULL`) so the same code can
    never be redeemed twice, including under concurrent requests. Raises
    `InvalidMfaCode` if neither check passes.
    """
    with tenant_context(app_db, company_id):
        row = app_db.execute(
            text("SELECT mfa_secret_enc, mfa_enabled_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).first()
        if row is None or row.mfa_enabled_at is None or row.mfa_secret_enc is None:
            raise MfaNotEnabled("MFA is not enabled for this user")

        try:
            secret = decrypt_secret(row.mfa_secret_enc)
        except InvalidCiphertext as exc:
            raise InvalidMfaCode("invalid authentication code") from exc

        if pyotp.TOTP(secret).verify(code, valid_window=1):
            app_db.commit()
            return

        candidates = app_db.execute(
            text(
                """
                SELECT id, code_hash FROM mfa_backup_codes
                 WHERE company_id = :cid AND user_id = :uid AND used_at IS NULL
                """
            ),
            {"cid": company_id, "uid": user_id},
        ).all()
        for candidate in candidates:
            if verify_backup_code(code, candidate.code_hash):
                claimed = app_db.execute(
                    text(
                        """
                        UPDATE mfa_backup_codes
                           SET used_at = now()
                         WHERE id = :id AND used_at IS NULL
                        RETURNING id
                        """
                    ),
                    {"id": candidate.id},
                ).first()
                if claimed is not None:
                    app_db.commit()
                    return
                break  # lost a race to claim this one code; fall through to failure

        app_db.rollback()
        raise InvalidMfaCode("invalid authentication code")


def remaining_backup_code_count(
    app_db: Session, *, company_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    with tenant_context(app_db, company_id):
        row = app_db.execute(
            text(
                """
                SELECT count(*) AS n FROM mfa_backup_codes
                 WHERE company_id = :cid AND user_id = :uid AND used_at IS NULL
                """
            ),
            {"cid": company_id, "uid": user_id},
        ).first()
    return int(row.n) if row is not None else 0
