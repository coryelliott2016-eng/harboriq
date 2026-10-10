"""Repository integrity checker regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_repo_integrity import (
    _file_integrity_errors,
    _is_binary,
    _skill_integrity_errors,
)


@pytest.mark.no_db
def test_file_integrity_check_rejects_bytecode_and_unexpected_binaries(tmp_path):
    (tmp_path / "cache.pyc").write_bytes(b"compiled")
    (tmp_path / "payload.dat").write_bytes(b"\x01\x02\x03\x04")
    (tmp_path / "logo.png").write_bytes(b"\x00image")
    paths = [Path("cache.pyc"), Path("payload.dat"), Path("logo.png")]

    errors = _file_integrity_errors(tmp_path, paths)

    assert errors == [
        "tracked Python bytecode: cache.pyc",
        "unallowlisted binary file: payload.dat",
    ]


@pytest.mark.no_db
def test_binary_detection_catches_non_utf8_and_control_bytes():
    assert _is_binary(b"\xff\xfe")
    assert _is_binary(b"\x01\x02\x03\x04")
    assert not _is_binary(b"valid UTF-8 text\n")


@pytest.mark.no_db
def test_skill_inventory_requires_registered_matching_hashes(tmp_path):
    skill = tmp_path / ".github/skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("A registered skill.\n", encoding="utf-8")
    manifest = tmp_path / ".github/skills/manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skills": [
                    {
                        "path": ".github/skills/example/SKILL.md",
                        "sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _skill_integrity_errors(tmp_path) == []

    skill.write_text("Changed without updating the lock.\n", encoding="utf-8")
    assert _skill_integrity_errors(tmp_path) == [
        "skill integrity hash mismatch: .github/skills/example/SKILL.md"
    ]
