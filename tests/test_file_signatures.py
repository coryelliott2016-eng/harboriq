"""Unit tests for app.core.file_signatures (Security Core Prompt v1.0, M-3)."""
from __future__ import annotations

from app.core.file_signatures import (
    ALLOWED_ATTACHMENT_CONTENT_TYPES,
    matches_declared_type,
)

_JPEG = b"\xff\xd8\xff\xe0" + b"rest-of-jpeg-bytes"
_PNG = b"\x89PNG\r\n\x1a\n" + b"rest-of-png-bytes"
_GIF87 = b"GIF87a" + b"rest-of-gif-bytes"
_GIF89 = b"GIF89a" + b"rest-of-gif-bytes"
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"rest-of-webp-bytes"
_HTML = b"<html><body>not an image</body></html>"
_ELF = b"\x7fELF" + b"\x00" * 12


def test_allowlist_is_images_only():
    assert ALLOWED_ATTACHMENT_CONTENT_TYPES == {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }


def test_jpeg_matches_its_own_declared_type():
    assert matches_declared_type(_JPEG, "image/jpeg") is True


def test_png_matches_its_own_declared_type():
    assert matches_declared_type(_PNG, "image/png") is True


def test_gif87_and_gif89_both_match_image_gif():
    assert matches_declared_type(_GIF87, "image/gif") is True
    assert matches_declared_type(_GIF89, "image/gif") is True


def test_webp_matches_its_own_declared_type():
    assert matches_declared_type(_WEBP, "image/webp") is True


def test_html_payload_does_not_match_any_declared_image_type():
    for content_type in ALLOWED_ATTACHMENT_CONTENT_TYPES:
        assert matches_declared_type(_HTML, content_type) is False


def test_elf_binary_does_not_match_any_declared_image_type():
    for content_type in ALLOWED_ATTACHMENT_CONTENT_TYPES:
        assert matches_declared_type(_ELF, content_type) is False


def test_cross_type_mismatch_is_rejected():
    """A real JPEG mislabeled as PNG (or vice versa) must not match --
    otherwise a caller could bypass the allowlist by pairing valid magic
    bytes for one type with a different declared type down the line."""
    assert matches_declared_type(_JPEG, "image/png") is False
    assert matches_declared_type(_PNG, "image/jpeg") is False


def test_unknown_content_type_never_matches():
    assert matches_declared_type(_JPEG, "application/pdf") is False
    assert matches_declared_type(_JPEG, "text/html") is False
