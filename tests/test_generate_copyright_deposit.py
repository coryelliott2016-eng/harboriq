from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_copyright_deposit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_copyright_deposit", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _truncate():
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    yield


@pytest.fixture(autouse=True, scope="session")
def _celery_eager_mode():
    yield


def test_main_writes_first_and_last_ten_pages_with_correct_cfr_citation(tmp_path):
    module = _load_module()

    repo_root = tmp_path / "repo"
    (repo_root / "app").mkdir(parents=True)
    (repo_root / "frontend" / "src").mkdir(parents=True)
    (repo_root / "docs").mkdir()

    app_lines = [f"backend line {i}" for i in range(1, 421)]
    frontend_lines = [f"frontend line {i}" for i in range(1, 421)]

    (repo_root / "app" / "service.py").write_text("\n".join(app_lines) + "\n", encoding="utf-8")
    (repo_root / "frontend" / "src" / "screen.ts").write_text(
        "\n".join(frontend_lines) + "\n",
        encoding="utf-8",
    )
    (repo_root / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (repo_root / "LICENSE").write_text("Copyright (c) 2026 Test Owner\n", encoding="utf-8")

    module.REPO_ROOT = repo_root
    module.main()

    output = (repo_root / "docs" / "copyright_deposit_first10_last10.txt").read_text(encoding="utf-8")
    output_lines = output.splitlines()

    assert "37 C.F.R. 202.20(c)(2)(vii)(A)(2))." in output
    assert "FIRST 10 PAGES (400 LINES)" in output
    assert "LAST 10 PAGES (400 LINES)" in output
    assert "Total lines in full combined source listing: 844" in output
    assert "[... 44 lines omitted per trade-secret deposit rules ...]" in output
    assert "backend line 1" in output_lines
    assert "backend line 398" in output_lines
    assert "backend line 400" not in output_lines
    assert "frontend line 21" not in output_lines
    assert "frontend line 22" in output_lines
    assert "frontend line 420" in output_lines
