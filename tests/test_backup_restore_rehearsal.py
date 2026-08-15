"""Backup / restore rehearsal — blocking CI gate.

An untested backup is not a backup. This test is the CI counterpart to
`scripts/rehearse_backup_restore.sh`: it invokes the same rehearsal script
against the CI Postgres service container (which is already seeded with
whatever schema Alembic's `upgrade head` step ran, plus whatever rows the
rest of the tests in this run have created and left behind by the time
pytest picks this file up in collection order) and asserts a successful
end-to-end round trip.

This is intentionally an integration test that shells out to the real
scripts rather than a unit test of either backup_db.sh or restore_db_s3.sh
alone. The class of failure this exists to catch (a dump that psql refuses
to reload because of ON_ERROR_STOP, a missing extension on the restore
side, a schema-search-path mismatch, a pg_dump/psql version drift) only
shows up on the seam between the two scripts, not inside either one.

Prerequisites (present in CI, documented for local runs):
  * `postgres`, `psql`, `pg_dump`, `gunzip` on PATH.
  * A DB superuser (or CREATEDB) connection URL exposed via env var
    `REHEARSAL_ADMIN_URL`. In CI this is set from the workflow's known
    `postgres://postgres:postgres@localhost:5432/postgres` credential.
  * The `SERVICE_DATABASE_URL` env var already set for the main test suite,
    used unchanged as the source URL for the backup step.

The test skips (rather than fails) when `REHEARSAL_ADMIN_URL` is unset, so
a local `pytest` run against a plain `docker compose up -d db` (which
gives the developer their normal harboriq_app/harboriq_service roles but
not necessarily a discoverable superuser URL) does not spuriously fail
this file. CI must set REHEARSAL_ADMIN_URL to keep the gate blocking.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REHEARSAL_SCRIPT = REPO_ROOT / "scripts" / "rehearse_backup_restore.sh"


def _tool_on_path(name: str) -> bool:
    return shutil.which(name) is not None


@pytest.mark.skipif(
    not os.environ.get("REHEARSAL_ADMIN_URL"),
    reason="REHEARSAL_ADMIN_URL not set — rehearsal gate skipped (set it in CI to keep blocking)",
)
@pytest.mark.skipif(
    not all(_tool_on_path(t) for t in ("psql", "pg_dump", "gunzip", "bash")),
    reason="rehearsal requires psql, pg_dump, gunzip, and bash on PATH",
)
def test_backup_restore_round_trip():
    """Dump the CI DB, restore into a scratch DB, verify schema+row counts.

    The rehearsal script is the source of truth for what "successful round
    trip" means — this test just runs it, captures its output for the CI
    log, and asserts exit 0. Any regression in either backup_db.sh or
    restore_db_s3.sh that breaks the round trip will surface here.
    """
    from app.core.config import settings

    env = os.environ.copy()
    env["REHEARSAL_ADMIN_URL"] = os.environ["REHEARSAL_ADMIN_URL"]
    # The main suite already has SERVICE_DATABASE_URL wired up in
    # app/core/config.py; source that instead of re-reading env directly so
    # a local override in .env is honored consistently with everything else.
    env["REHEARSAL_SOURCE_URL"] = settings.service_database_url
    # Deterministic scratch DB name per test invocation. Matches
    # restore_db_s3.sh's production-shape guard (contains "rehearsal") so
    # no RESTORE_CONFIRM env var is needed.
    env["REHEARSAL_SCRATCH_DB"] = f"harboriq_rehearsal_pytest_{os.getpid()}"

    # Resolve `bash` to a full path so ruff's S607 (partial-path executable)
    # rule stays happy; the executable and its one script argument are both
    # constants under this repo's control (no untrusted input), so the
    # matching S603 warning is a false positive that we suppress with a
    # justification rather than blanket-disabling.
    bash_path = shutil.which("bash")
    assert bash_path is not None  # already guarded by the skipif above
    result = subprocess.run(  # noqa: S603 -- args are constants, not untrusted input
        [bash_path, str(REHEARSAL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    # Always attach both streams to the CI log so a real failure is
    # diagnosable without re-running with -s.
    if result.stdout:
        print("--- rehearse_backup_restore.sh stdout ---")
        print(result.stdout)
    if result.stderr:
        print("--- rehearse_backup_restore.sh stderr ---")
        print(result.stderr)

    assert result.returncode == 0, (
        f"backup/restore rehearsal failed (exit {result.returncode}); "
        f"see stdout/stderr above for the failing step"
    )
