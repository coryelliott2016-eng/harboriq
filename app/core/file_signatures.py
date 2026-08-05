"""Magic-byte (file-signature) sniffing for uploaded attachments.

Security Core Prompt v1.0, M-3 fix: job attachments previously trusted the
client-supplied `content_type` string with no validation against the actual
bytes -- a caller could label an arbitrary payload (e.g. an HTML document
carrying a stored-XSS payload, or an executable) as `image/jpeg` and have it
accepted, stored, and later served back with that same `content_type` header
to another user's browser.

Deliberately dependency-free (no `python-magic`/libmagic system dependency --
same reasoning `pyproject.toml` already documents for choosing reportlab over
weasyprint: this must install identically everywhere `pip install` works,
including minimal container/CI images with no native libs). Attachments are
restricted to a small, fixed set of image formats a phone camera or an
in-browser signature-pad canvas actually produces, so a handful of well-known
magic-byte prefixes fully cover the legitimate input space.
"""
from __future__ import annotations

# Canonical content-type -> the one signature we accept for it. Deliberately
# a strict 1:1 allowlist (not "sniff and trust whatever we detect") so a
# request cannot smuggle a mismatched pair like
# content_type="image/png" + actual JPEG bytes past validation.
ALLOWED_ATTACHMENT_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)


def _is_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_gif(data: bytes) -> bool:
    return data[:6] in (b"GIF87a", b"GIF89a")


def _is_webp(data: bytes) -> bool:
    # RIFF container, byte offset 8-11 must be "WEBP" (RFC: RIFF <size> WEBP).
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


_SNIFFERS = {
    "image/jpeg": _is_jpeg,
    "image/png": _is_png,
    "image/webp": _is_webp,
    "image/gif": _is_gif,
}


def matches_declared_type(raw_bytes: bytes, declared_content_type: str) -> bool:
    """True iff `raw_bytes` starts with the magic bytes for `declared_content_type`.

    Callers must check `declared_content_type in ALLOWED_ATTACHMENT_CONTENT_TYPES`
    first (or treat an unknown type here as a rejection) -- an unrecognized
    content type has no sniffer and is never accepted by this function alone.
    """
    sniffer = _SNIFFERS.get(declared_content_type)
    if sniffer is None:
        return False
    return sniffer(raw_bytes)
