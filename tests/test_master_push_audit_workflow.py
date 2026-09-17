from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "master-push-audit.yml"


@pytest.fixture(autouse=True)
def _truncate():
    yield


def test_master_push_audit_workflow_links_matching_ci_run():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'actions/workflows/ci.yml/runs?branch=${BRANCH}&event=push&per_page=20' in text
    assert 'select(.head_sha == env.SHA)' in text
    assert "| Audit run | [audit workflow]($AUDIT_RUN_URL) |" in text
    assert "| CI workflow | ${CI_RUN_CELL} |" in text
