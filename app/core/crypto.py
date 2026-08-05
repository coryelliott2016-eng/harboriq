"""Symmetric at-rest encryption for narrow, specific secrets (Phase 16).

This is NOT a general-purpose crypto helper. It exists for exactly one job
today: encrypting `users.mfa_secret_enc`, the raw TOTP shared secret, before
it touches the database. A TOTP secret is different from a password (which
is hashed, one-way, via `app/core/security.py`'s Argon2id) because the
server must recover the *original* secret to verify future codes and to
show it again during re-enrollment flows -- hashing would make that
impossible, so it needs reversible encryption instead.

Algorithm: Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography`
package) -- authenticated, versioned, and includes its own IV/timestamp
handling. Deliberately not rolling anything lower-level by hand.

Key management: `settings.effective_mfa_encryption_key` (see
app/core/config.py) -- a single 32-byte urlsafe-base64 Fernet key from the
MFA_ENCRYPTION_KEY env var, with a fixed insecure placeholder substituted
only when APP_ENV=development. Non-development environments are required
(via a pydantic-settings validator) to set a real key.

Key rotation: Fernet has no built-in multi-key/versioning support, so a
future rotation without invalidating every enrolled user's TOTP secret
would need `cryptography.fernet.MultiFernet` (accepts a *list* of keys --
newest first for encryption, all tried in order for decryption). Not
implemented today because there is exactly one key in play; documented here
so the upgrade path is obvious when it's needed (see README "Auth" /
docs/DEPLOYMENT.md "MFA / TOTP").
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

__all__ = ["encrypt_secret", "decrypt_secret", "InvalidToken"]


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(settings.effective_mfa_encryption_key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt a secret (e.g. a base32 TOTP secret) for storage."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    """Decrypt a value previously produced by `encrypt_secret`.

    Raises `InvalidToken` (from `cryptography.fernet`) if the ciphertext is
    corrupt or was encrypted under a different key -- callers should treat
    that as an unrecoverable server-side data problem, not a user error.
    """
    return _fernet().decrypt(ciphertext).decode("utf-8")
