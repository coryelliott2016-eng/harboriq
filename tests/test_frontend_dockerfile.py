"""Guard the frontend Docker build's npm peer-dependency compatibility.

`npm ci` in frontend/Dockerfile relies on frontend/.npmrc's
`legacy-peer-deps=true` to satisfy eslint-plugin-jsx-a11y's eslint peer
range (stops at ^9) against this project's eslint@^10. That only works if
`.npmrc` is copied into the build stage *before* `npm ci` runs — copying it
later with the full `COPY . .` is too late, and the build fails with an
ERESOLVE conflict (CI run 35661763380). These tests pin that invariant.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _dockerfile_instructions() -> list[str]:
    """Return the Dockerfile's instruction lines (comments/blanks stripped)."""
    lines = (FRONTEND / "Dockerfile").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def test_npmrc_sets_legacy_peer_deps() -> None:
    npmrc = (FRONTEND / ".npmrc").read_text()
    assert "legacy-peer-deps=true" in npmrc


def test_npmrc_copied_before_npm_ci() -> None:
    instructions = _dockerfile_instructions()
    npm_ci_idx = next(
        i for i, ln in enumerate(instructions) if ln.startswith("RUN") and "npm ci" in ln
    )
    copies_before = [
        ln for ln in instructions[:npm_ci_idx] if ln.startswith("COPY") and ".npmrc" in ln
    ]
    assert copies_before, (
        "frontend/Dockerfile must COPY .npmrc before `RUN npm ci`, otherwise npm "
        "ignores legacy-peer-deps=true and fails with an ERESOLVE conflict"
    )


def test_dockerignore_does_not_exclude_npmrc() -> None:
    entries = [
        ln.strip()
        for ln in (FRONTEND / ".dockerignore").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert ".npmrc" not in entries
    assert "*.npmrc" not in entries
