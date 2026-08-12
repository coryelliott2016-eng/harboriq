#!/usr/bin/env python3
"""HarborIQ security-control drift scan.

Purpose
-------
A lightweight, dependency-free re-check that the compensating and
remediated controls documented in
`reports/HarborIQ_Security_Audit_2026-08-05.md` (project file repo) and
`concepts/harboriq-security-standard.md` (project wiki) are still actually
present in the codebase -- not a re-run of the full audit or the full test
suite. Designed to be run periodically (see the scheduled task that invokes
it) against a fresh, read-only clone, with no live Postgres/Redis
dependency, so it can run unattended and cheaply.

This intentionally checks *static* evidence (source, migrations, CI config,
GitHub repo settings) rather than re-deriving findings from scratch. Static
checks catch the actual failure mode this project has repeatedly hit: an
independent/parallel commit silently reverting or bypassing a control that
a previous audit fixed (e.g. re-adding `|| true` to a blocking CI step, a
new migration re-granting `harboriq_app` on a service-only table, deleting
a regression test). It is not a substitute for periodically re-running the
full audit methodology by hand.

Exit code: 0 if every "must not regress" control still passes (H-6 branch
protection is tracked separately -- see below). Non-zero if any regression
is found, so a scheduling wrapper can alert on a non-zero exit without
having to parse output.

Usage:
    python3 scripts/security_drift_scan.py [--repo-path PATH] [--state-file PATH]

`--state-file` stores the last-observed status of items that are *known,
accepted-open* (currently just H-6) so the wrapper only has to alert on a
*change* in those, not on every run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    id: str
    title: str
    status: str  # "PASS" | "FAIL" | "SKIP" | "INFO"
    detail: str
    group: str  # "regression" (must not regress) | "tracked" (known open item)


@dataclass
class ScanReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, *args, **kwargs) -> None:
        self.results.append(CheckResult(*args, **kwargs))

    def regressions(self) -> list[CheckResult]:
        return [r for r in self.results if r.group == "regression" and r.status == "FAIL"]

    def tracked(self) -> list[CheckResult]:
        return [r for r in self.results if r.group == "tracked"]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _grep_any(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


# ---------------------------------------------------------------------------
# Group A -- controls that were fixed by a specific audit commit and must
# not silently regress. Each check greps for the concrete evidence the
# original commit introduced, not just a keyword -- e.g. it checks that the
# blocking `pip-audit`/`npm audit` CI steps do NOT have `|| true` reattached,
# not merely that the word "pip-audit" appears somewhere.
# ---------------------------------------------------------------------------

def check_stripe_webhook_signature(repo: Path, report: ScanReport) -> None:
    text = _read(repo / "app" / "api" / "v1" / "routes" / "stripe_webhook.py")
    if not text:
        # Fall back to a repo-wide search in case the route file moved.
        candidates = list(repo.rglob("*stripe*webhook*.py"))
        text = "".join(_read(p) for p in candidates)
    ok = "construct_event" in text and "stripe.Webhook" in text
    report.add(
        "C-1", "Stripe webhook signature verification",
        "PASS" if ok else "FAIL",
        "stripe.Webhook.construct_event present" if ok else "construct_event call not found",
        "regression",
    )


def check_twilio_webhook_fail_closed(repo: Path, report: ScanReport) -> None:
    candidates = [
        p for p in (list(repo.rglob("sms_webhooks.py")) + list(repo.rglob("*twilio*.py")))
        if "test" not in p.name and "__pycache__" not in str(p)
    ]
    text = "".join(_read(p) for p in candidates)
    ok = _grep_any(text, r"X-Twilio-Signature|verify_twilio_signature") and _grep_any(
        text, r"app_env\s*!=\s*[\"']development[\"']"
    )
    report.add(
        "M-1", "Twilio webhook fails closed outside development",
        "PASS" if ok else "FAIL",
        "signature check + environment gate found" if ok else "signature/environment gate not found",
        "regression",
    )


def check_security_headers(repo: Path, report: ScanReport) -> None:
    text = _read(repo / "app" / "main.py")
    ok = "SecurityHeadersMiddleware" in text
    report.add(
        "H-3", "HTTP security headers middleware",
        "PASS" if ok else "FAIL",
        "SecurityHeadersMiddleware wired in app/main.py" if ok else "SecurityHeadersMiddleware not found in app/main.py",
        "regression",
    )


def check_ci_blocking_scans(repo: Path, report: ScanReport) -> None:
    ci = _read(repo / ".github" / "workflows" / "ci.yml")
    has_gitleaks = "gitleaks" in ci.lower()
    # A regression looks like `pip-audit ... || true` or `npm audit ... || true`
    # reappearing on the same line as the scan command.
    audit_lines = [
        ln for ln in ci.splitlines()
        if ("pip-audit" in ln or "npm audit" in ln or "audit-ci" in ln) and not ln.strip().startswith("#")
    ]
    weakened = [ln for ln in audit_lines if "|| true" in ln or "continue-on-error: true" in ln]
    ok = has_gitleaks and bool(audit_lines) and not weakened
    detail = (
        "gitleaks + blocking dependency-audit steps present"
        if ok
        else f"gitleaks={has_gitleaks}, audit_lines={len(audit_lines)}, weakened_lines={weakened or 'none'}"
    )
    report.add("H-5", "CI secret-scan + dependency-audit are blocking, not advisory", "PASS" if ok else "FAIL", detail, "regression")

    ruff_cfg = _read(repo / "pyproject.toml")
    s_rules = bool(re.search(r'select\s*=\s*\[[^\]]*"S"', ruff_cfg, re.DOTALL)) or '"S"' in ruff_cfg
    report.add(
        "H-5b", "ruff bandit-derived (S) rules enabled",
        "PASS" if s_rules else "FAIL",
        "\"S\" ruleset found in pyproject.toml" if s_rules else "\"S\" ruleset not found in pyproject.toml",
        "regression",
    )


def check_file_signature_validation(repo: Path, report: ScanReport) -> None:
    sig_module = repo / "app" / "core" / "file_signatures.py"
    ok = sig_module.exists() and "matches_declared_type" in _read(sig_module)
    used = "matches_declared_type" in _read(repo / "app" / "schemas" / "field_app.py")
    status = "PASS" if (ok and used) else "FAIL"
    report.add(
        "M-3", "Upload MIME allowlist + magic-byte validation",
        status,
        "file_signatures module present and used by field_app schema" if status == "PASS" else "magic-byte validation missing or unused",
        "regression",
    )


def check_rls_service_only_revoke(repo: Path, report: ScanReport) -> None:
    """M-2: the two service-only webhook ledgers must stay revoked from the
    app role. A regression looks like a *later* migration re-granting
    harboriq_app on either table (e.g. a broad `GRANT ALL ON ALL TABLES`
    added after 0022 without a matching exclusion).
    """
    sql_dir = repo / "alembic" / "sql"
    revoke_file = sql_dir / "0022_service_only_webhook_tables.sql"
    revoke_text = _read(revoke_file)
    has_revoke = bool(revoke_file.exists()) and "REVOKE" in revoke_text.upper() and "harboriq_app" in revoke_text

    # Any migration numbered higher than 0022 that grants broadly to
    # harboriq_app on ALL TABLES (which would silently re-include the two
    # service-only tables) is a regression signal.
    later_broad_grants = []
    for sql_file in sorted(sql_dir.glob("0*.sql")):
        try:
            num = int(sql_file.name.split("_", 1)[0])
        except ValueError:
            continue
        if num <= 22:
            continue
        text = _read(sql_file)
        if re.search(r"GRANT\s+.*ON\s+ALL\s+TABLES.*harboriq_app", text, re.IGNORECASE | re.DOTALL):
            later_broad_grants.append(sql_file.name)

    test_present = (repo / "tests" / "test_rls_coverage.py").exists()
    ok = has_revoke and not later_broad_grants and test_present
    detail_bits = [
        f"0022 revoke present={has_revoke}",
        f"later_broad_grants={later_broad_grants or 'none'}",
        f"test_rls_coverage.py present={test_present}",
    ]
    report.add("M-2", "Service-only webhook tables stay revoked from app role", "PASS" if ok else "FAIL", "; ".join(detail_bits), "regression")


def check_metrics_auth(repo: Path, report: ScanReport) -> None:
    main_text = _read(repo / "app" / "main.py")
    config_text = _read(repo / "app" / "core" / "config.py")
    has_gate = "metrics_token" in main_text and "compare_digest" in main_text
    has_validator = "_require_metrics_token_outside_development" in config_text
    test_present = (repo / "tests" / "test_metrics.py").exists() and "Bearer" in _read(repo / "tests" / "test_metrics.py")
    ok = has_gate and has_validator and test_present
    report.add(
        "M-4", "/metrics requires METRICS_TOKEN bearer auth, fails closed outside dev",
        "PASS" if ok else "FAIL",
        f"gate={has_gate}, startup_validator={has_validator}, regression_test={test_present}",
        "regression",
    )


def check_rate_limiter(repo: Path, report: ScanReport) -> None:
    text = _read(repo / "app" / "core" / "rate_limit.py")
    ok = "redis" in text.lower() and "_RedisFixedWindowLimiter" in text
    report.add(
        "H-4", "Redis-backed distributed rate limiting",
        "PASS" if ok else "FAIL",
        "Redis-backed limiter class present" if ok else "Redis-backed limiter not found",
        "regression",
    )


def check_jti_denylist(repo: Path, report: ScanReport) -> None:
    ok = (repo / "app" / "core" / "token_denylist.py").exists()
    report.add(
        "Phase17", "Stateful access-token revocation (JTI denylist)",
        "PASS" if ok else "FAIL",
        "token_denylist.py present" if ok else "token_denylist.py missing",
        "regression",
    )


def check_push_audit_workflow(repo: Path, report: ScanReport) -> None:
    text = _read(repo / ".github" / "workflows" / "master-push-audit.yml")
    ok = bool(text) and "issue" in text.lower() and "master-push-audit" in text
    report.add(
        "H-6-compensating", "master-push-audit compensating control present",
        "PASS" if ok else "FAIL",
        "workflow present and creates tracking issues" if ok else "master-push-audit.yml missing or malformed",
        "regression",
    )


def check_codeowners(repo: Path, report: ScanReport) -> None:
    ok = (repo / ".github" / "CODEOWNERS").exists()
    report.add(
        "CODEOWNERS", "CODEOWNERS placeholder present",
        "PASS" if ok else "FAIL",
        "present" if ok else "missing",
        "regression",
    )


def check_location_ping_bounds(repo: Path, report: ScanReport) -> None:
    """Not a previously-fixed finding, but part of the 2026-08-11 marine
    threat model (technician/telemetry spoofing scenario) -- verifies the
    lat/long bounds validator on the location-ping schema is still in place,
    since it's the one input guard that exists today against garbage
    coordinates.
    """
    text = _read(repo / "app" / "schemas" / "dispatch_board.py")
    ok = bool(re.search(r"latitude.*ge=Decimal\([\"']-90[\"']\)", text)) and bool(
        re.search(r"longitude.*ge=Decimal\([\"']-180[\"']\)", text)
    )
    report.add(
        "TM-1", "location-ping lat/long bounds validation",
        "PASS" if ok else "FAIL",
        "bounds validator present" if ok else "bounds validator missing from LocationPing schema",
        "regression",
    )



def check_location_ping_rate_limit(repo: Path, report: ScanReport) -> None:
    """Marine threat model Scenario 2: per-user rate limit on location-ping."""
    rl = _read(repo / "app" / "core" / "rate_limit.py")
    route = _read(repo / "app" / "api" / "v1" / "routes" / "users.py")
    ok = (
        "enforce_location_ping_rate_limit" in rl
        and "_location_ping_limiter" in rl
        and "enforce_location_ping_rate_limit" in route
    )
    report.add(
        "TM-2", "location-ping per-user rate limit",
        "PASS" if ok else "FAIL",
        "limiter + route enforcement present" if ok else "location-ping rate limit missing",
        "regression",
    )


def check_location_ping_plausibility(repo: Path, report: ScanReport) -> None:
    """Marine threat model Scenario 2: implied-speed anomaly flagging."""
    svc = _read(repo / "app" / "services" / "users.py")
    schema = _read(repo / "app" / "schemas" / "dispatch_board.py")
    ok = (
        "_evaluate_location_anomaly" in svc
        and "_haversine_km" in svc
        and "anomaly_suspected" in schema
    )
    report.add(
        "TM-3", "location-ping speed plausibility check",
        "PASS" if ok else "FAIL",
        "haversine anomaly check + response flag present" if ok else "plausibility check missing",
        "regression",
    )


def check_logout_all_devices_access_epoch(repo: Path, report: ScanReport) -> None:
    """Marine threat model Scenario 1: all_devices kills other access tokens.

    Evidence: epoch bump on logout-all, ave claim at mint, stale-epoch check
    in deps. Without this, other devices' access tokens linger until exp.
    """
    denylist = _read(repo / "app" / "core" / "token_denylist.py")
    security = _read(repo / "app" / "core" / "security.py")
    deps = _read(repo / "app" / "api" / "deps.py")
    auth_svc = _read(repo / "app" / "services" / "auth.py")
    ok = (
        "bump_user_access_epoch" in denylist
        and "is_user_access_epoch_stale" in denylist
        and '"ave"' in security
        and "is_user_access_epoch_stale" in deps
        and "bump_user_access_epoch" in auth_svc
    )
    report.add(
        "TM-4", "logout all_devices invalidates other access tokens",
        "PASS" if ok else "FAIL",
        "access-epoch bump + JWT ave + deps check present" if ok else "access-epoch control missing",
        "regression",
    )



# ---------------------------------------------------------------------------
# Group B -- known, accepted-open items. We track *state changes*, not
# pass/fail, since these are documented as open in the audit report.
# ---------------------------------------------------------------------------

def check_branch_protection(report: ScanReport, repo_slug: str) -> str:
    """Returns a short status string: 'protected', 'unprotected', or
    'unknown' (gh not available/authenticated). Reported as INFO, not
    PASS/FAIL, since this is a known, tracked-open item (H-6), not a
    regression signal in isolation.
    """
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{repo_slug}/branches/master/protection"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        report.add("H-6", "Branch protection on master", "SKIP", "gh CLI unavailable", "tracked")
        return "unknown"

    if proc.returncode == 0:
        report.add("H-6", "Branch protection on master", "INFO", "protection API returned 200 -- appears ENABLED", "tracked")
        return "protected"
    if "403" in proc.stderr or "Upgrade to GitHub Pro" in proc.stderr:
        report.add("H-6", "Branch protection on master", "INFO", "still blocked: plan-gated 403 (known open item)", "tracked")
        return "unprotected"
    report.add("H-6", "Branch protection on master", "SKIP", f"unexpected gh response: {proc.stderr.strip()[:200]}", "tracked")
    return "unknown"


def check_dependabot_alerts(report: ScanReport, repo_slug: str) -> None:
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{repo_slug}/dependabot/alerts", "--jq", "[.[] | select(.state==\"open\")] | length"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        report.add("DEP-ALERTS", "Open Dependabot alerts", "SKIP", "gh CLI unavailable", "tracked")
        return
    if proc.returncode == 0 and proc.stdout.strip().isdigit():
        count = int(proc.stdout.strip())
        report.add(
            "DEP-ALERTS", "Open Dependabot alerts",
            "INFO" if count == 0 else "FAIL",
            f"{count} open alert(s)",
            "regression" if count > 0 else "tracked",
        )
    else:
        report.add("DEP-ALERTS", "Open Dependabot alerts", "SKIP", "Dependabot alerts API not available on this plan/repo", "tracked")


# ---------------------------------------------------------------------------

def run_all_checks(repo: Path, repo_slug: str | None) -> ScanReport:
    report = ScanReport()
    check_stripe_webhook_signature(repo, report)
    check_twilio_webhook_fail_closed(repo, report)
    check_security_headers(repo, report)
    check_ci_blocking_scans(repo, report)
    check_file_signature_validation(repo, report)
    check_rls_service_only_revoke(repo, report)
    check_metrics_auth(repo, report)
    check_rate_limiter(repo, report)
    check_jti_denylist(repo, report)
    check_push_audit_workflow(repo, report)
    check_codeowners(repo, report)
    check_location_ping_bounds(repo, report)
    check_location_ping_rate_limit(repo, report)
    check_location_ping_plausibility(repo, report)
    check_logout_all_devices_access_epoch(repo, report)
    if repo_slug:
        check_branch_protection(report, repo_slug)
        check_dependabot_alerts(report, repo_slug)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", default=".", help="Path to a HarborIQ checkout")
    parser.add_argument("--repo-slug", default="coryelliott2016-eng/harboriq", help="owner/repo for GitHub API checks (omit checks with --no-github)")
    parser.add_argument("--no-github", action="store_true", help="Skip GitHub API checks (branch protection, Dependabot)")
    parser.add_argument("--state-file", default=None, help="Path to persist tracked-item state across runs")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human-readable report")
    args = parser.parse_args()

    repo = Path(args.repo_path).resolve()
    slug = None if args.no_github else args.repo_slug
    report = run_all_checks(repo, slug)

    regressions = report.regressions()

    if args.state_file:
        state_path = Path(args.state_file)
        prev_state = {}
        if state_path.exists():
            try:
                prev_state = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                prev_state = {}
        new_state = {r.id: r.detail for r in report.tracked()}
        changed = {k: (prev_state.get(k), v) for k, v in new_state.items() if prev_state.get(k) != v}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(new_state, indent=2))
    else:
        changed = {}

    if args.json:
        print(json.dumps(
            {
                "results": [r.__dict__ for r in report.results],
                "regressions": [r.id for r in regressions],
                "tracked_state_changes": changed,
            },
            indent=2,
        ))
    else:
        print("HarborIQ security drift scan")
        print("=" * 60)
        for r in report.results:
            print(f"[{r.status:4}] {r.id:16} {r.title}")
            print(f"         {r.detail}")
        print("=" * 60)
        if regressions:
            print(f"REGRESSIONS DETECTED: {', '.join(r.id for r in regressions)}")
        else:
            print("No regressions detected among tracked controls.")
        if changed:
            print(f"Tracked-item state changed since last run: {changed}")

    return 1 if (regressions or changed) else 0


if __name__ == "__main__":
    sys.exit(main())
