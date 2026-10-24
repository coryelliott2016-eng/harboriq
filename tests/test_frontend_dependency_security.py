"""Regression checks for frontend dependency-audit guardrails."""
from __future__ import annotations

import json
from pathlib import Path

import pytest



def _parse_version(version: str) -> tuple[int, int, int]:
    cleaned = version.strip().lstrip("^~>=<")
    major, minor, patch = cleaned.split(".")[:3]
    return int(major), int(minor), int(patch)


@pytest.mark.no_db
def test_capacitor_mobile_packages_are_not_in_known_vulnerable_range() -> None:
    package_json = json.loads(Path("frontend/package.json").read_text())

    for package_name in ("@capacitor/android", "@capacitor/ios"):
        version = package_json["dependencies"][package_name]
        assert _parse_version(version) >= (8, 5, 1)


@pytest.mark.no_db
def test_frontend_overrides_pin_patched_transitive_security_versions() -> None:
    package_json = json.loads(Path("frontend/package.json").read_text())
    overrides = package_json["overrides"]

    assert _parse_version(overrides["source-map-js"]) >= (1, 2, 2)
    assert _parse_version(overrides["fast-uri"]) >= (3, 1, 9)
    assert _parse_version(overrides["undici"]) >= (7, 30, 1)
    assert _parse_version(overrides["zod"]) >= (4, 6, 7)
    assert _parse_version(overrides["brace-expansion@^1.1.7"]) >= (1, 1, 21)
    assert _parse_version(overrides["brace-expansion@^2.0.1"]) >= (2, 1, 7)
    assert _parse_version(overrides["brace-expansion@^5.0.1"]) >= (5, 0, 12)


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("package_name", "minimum_version"),
    [
        ("fast-uri", (3, 1, 9)),
        ("undici", (7, 30, 1)),
        ("zod", (4, 6, 7)),
    ],
)
def test_frontend_lockfile_resolves_patched_security_versions(
    package_name: str, minimum_version: tuple[int, int, int],
) -> None:
    lockfile = json.loads(Path("frontend/package-lock.json").read_text())
    versions = [
        package["version"]
        for path, package in lockfile["packages"].items()
        if path.endswith(f"node_modules/{package_name}")
    ]

    assert versions, f"{package_name} missing from lockfile"
    assert all(_parse_version(version) >= minimum_version for version in versions)
