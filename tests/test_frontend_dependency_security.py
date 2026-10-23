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
    assert _parse_version(overrides["undici"]) >= (7, 29, 1)
    assert _parse_version(overrides["brace-expansion@^1.1.7"]) >= (1, 1, 21)
    assert _parse_version(overrides["brace-expansion@^2.0.1"]) >= (2, 1, 7)
    assert _parse_version(overrides["brace-expansion@^5.0.1"]) >= (5, 0, 12)


@pytest.mark.no_db
def test_vitest_is_not_in_vulnerable_mocker_range() -> None:
    package_json = json.loads(Path("frontend/package.json").read_text())

    assert _parse_version(package_json["devDependencies"]["vitest"]) >= (4, 1, 12)
