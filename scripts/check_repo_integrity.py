#!/usr/bin/env python3
"""Check tracked source hygiene and repository-local skill integrity."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

BYTECODE_SUFFIXES = {".pyc", ".pyo"}
COMPILED_SUFFIXES = {
    ".a",
    ".class",
    ".dll",
    ".exe",
    ".o",
    ".so",
}
ALLOWED_BINARY_SUFFIXES = {".pdf", ".png"}
ALLOWED_BINARY_PATHS = {"frontend/android/gradle/wrapper/gradle-wrapper.jar"}
SKILLS_MANIFEST = Path(".github/skills/manifest.json")


def _tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def _is_binary(content: bytes) -> bool:
    if b"\0" in content:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _file_integrity_errors(root: Path, paths: list[Path]) -> list[str]:
    errors = []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        relative_name = relative.as_posix()
        if "__pycache__" in relative.parts or suffix in BYTECODE_SUFFIXES:
            errors.append(f"tracked Python bytecode: {relative_name}")
            continue
        if suffix in COMPILED_SUFFIXES and relative_name not in ALLOWED_BINARY_PATHS:
            errors.append(f"tracked compiled artifact: {relative_name}")
            continue
        if (
            _is_binary(path.read_bytes())
            and suffix not in ALLOWED_BINARY_SUFFIXES
            and relative_name not in ALLOWED_BINARY_PATHS
        ):
            errors.append(f"unallowlisted binary file: {relative_name}")
    return errors


def _skill_integrity_errors(root: Path) -> list[str]:
    manifest_path = root / SKILLS_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read skill manifest {SKILLS_MANIFEST}: {exc}"]

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return [f"unsupported skill manifest schema in {SKILLS_MANIFEST}"]
    entries = manifest.get("skills")
    if not isinstance(entries, list):
        return [f"'skills' must be a list in {SKILLS_MANIFEST}"]

    errors = []
    locked: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("each skill manifest entry must be an object")
            continue
        skill_path = entry.get("path")
        digest = entry.get("sha256")
        if (
            not isinstance(skill_path, str)
            or not skill_path.startswith(".github/skills/")
            or not skill_path.endswith("/SKILL.md")
            or ".." in Path(skill_path).parts
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            errors.append(f"invalid skill manifest entry: {entry!r}")
            continue
        if skill_path in locked:
            errors.append(f"duplicate skill manifest path: {skill_path}")
            continue
        locked[skill_path] = digest

    skill_root = root / ".github" / "skills"
    discovered = {
        path.relative_to(root).as_posix()
        for path in skill_root.glob("*/SKILL.md")
        if path.is_file()
    }
    for skill_path in sorted(discovered - locked.keys()):
        errors.append(f"unregistered repository skill: {skill_path}")
    for skill_path in sorted(locked.keys() - discovered):
        errors.append(f"missing registered repository skill: {skill_path}")
    for skill_path, expected_digest in locked.items():
        path = root / skill_path
        if not path.is_file():
            continue
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            errors.append(f"skill integrity hash mismatch: {skill_path}")
    return errors


def check_repository(root: Path) -> list[str]:
    try:
        tracked = _tracked_paths(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"cannot enumerate tracked files: {exc}"]
    return _file_integrity_errors(root, tracked) + _skill_integrity_errors(root)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = check_repository(root)
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print("Repository bytecode, binary, and skill-integrity checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
