# HarborIQ backend production launch audit

**Audit time:** 2026-08-15 (EDT)  
**Repository:** `/home/user/workspace/harboriq_repo`  
**Scope:** read-mostly validation only. No source files were edited or committed; `git status --short` and `git diff --stat` were empty after the audit. The virtual environment was augmented only with `pytest-timeout` (needed to run the requested test invocation) and `pip-audit` (explicitly requested).

## Gate results

| Gate | Result | Evidence / result |
|---|---|---|
| 1. Full backend suite | **FAIL — not verified** | The requested invocation initially exited **4** because `pytest-timeout` was absent. After installing that plugin, the same command still had no result after 11m44s (the execution environment returned its 630-second limit while the process continued); it was stopped to prevent an unbounded destructive run against the configured test DB. Full collection succeeds and reports **741 tests**, but there is no clean full-suite pass or total-failure count. |
| 2. Ruff lint | **PASS** | `All checks passed!` (exit 0). |
| 3. Clean-database migrations | **PASS** | A fresh disposable database upgraded through every revision to `0023 (head)`, downgraded one revision, and upgraded back to `0023 (head)`. The disposable database was dropped by the cleanup trap and its absence was verified. |
| 4. Dependency vulnerability audit | **FAIL** | `pip-audit` found **7 known vulnerabilities in 2 packages** (exit 1): five advisories for `pip 25.3`, and two for `pypdf 6.14.2`. |
| 5. Environment-variable inventory | **FAIL — template drift** | The Settings model has 17 environment variables absent from `.env.example`; listed below. |
| 6. Launch-blocker inspection | **FAIL** | Stripe signature verification exists and the focused Stripe/RLS tests passed, but a Stripe Billing `invoice.payment_succeeded` handler remains an unimplemented TODO stub. |

## Exact commands and outputs

### 1. Full backend tests

Initial requested command:

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pytest tests -x -q --timeout=300 2>&1 | tail -30
```

Result: exit **4**:

```text
ERROR: usage: python -m pytest [options] [file_or_dir] [file_or_dir] [...]
python -m pytest: error: unrecognized arguments: --timeout=300
```

Cause: `pytest-timeout` was not installed and is not declared under `[project.optional-dependencies].dev` in `pyproject.toml`. I ran the following environment-only prerequisite, without modifying project source:

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pip install pytest-timeout -q
```

It exited **0**. The requested test command was then rerun verbatim (with status capture appended):

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pytest tests -x -q --timeout=300 2>&1 | tail -30; test_status=${PIPESTATUS[0]}; printf '\n[pytest command exit=%s]\n' "$test_status"; exit "$test_status"
```

Result: the command produced no test result before the execution environment's 630-second deadline. At 11m44s it was still executing `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` in the autouse fixture, so it was stopped. Consequently, the required rerun without `-x` was **not started**: the first run never reached a failure or completion state, and starting a concurrent destructive full run would not provide a valid total-failure count. Full-suite failure count: **indeterminate**.

Supporting checks:

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pytest tests --collect-only -q 2>&1 | tail -5
```

Result: **741 tests collected in 1.01s**; one test skipped because `boto3` was not installed.

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pytest -q --timeout=300 tests/test_auth_rls.py tests/test_crm_rls.py tests/test_invoicing_rls.py tests/test_rls_coverage.py tests/test_rls_isolation.py tests/test_stripe_webhook_signature.py
```

Result: **49 passed in 98.13s** (exit 0).

### 2. Ruff

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m ruff check app tests
```

Result: `All checks passed!` (exit 0).

### 3. Clean-database migration and latest-revision reversibility

`alembic/env.py` prefers `SERVICE_DATABASE_URL` and accepts the SQLAlchemy psycopg URL format `postgresql+psycopg://...`. The disposable database was created with `harboriq_service` as owner:

```bash
cd /home/user/workspace/harboriq_repo
DB=harboriq_migrate_test_20260815
cleanup() { PGPASSWORD=postgres dropdb -h localhost -U postgres --if-exists "$DB"; }
trap cleanup EXIT
PGPASSWORD=postgres dropdb -h localhost -U postgres --if-exists "$DB"
PGPASSWORD=postgres createdb -h localhost -U postgres -O harboriq_service "$DB" || exit $?
export DATABASE_URL="postgresql+psycopg://harboriq_service:harboriq_service_pass@localhost:5432/$DB"
export SERVICE_DATABASE_URL="$DATABASE_URL"
.venv/bin/alembic upgrade head || exit $?
.venv/bin/alembic current || exit $?
.venv/bin/alembic downgrade -1 || exit $?
.venv/bin/alembic upgrade head || exit $?
.venv/bin/alembic current
```

Result: upgrades ran `0001 -> ... -> 0023`; `alembic current` returned `0023 (head)` before and after the `downgrade -1` / re-upgrade. The scratch database was confirmed absent after cleanup.

### 4. Dependency audit

```bash
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pip install pip-audit -q
cd /home/user/workspace/harboriq_repo && .venv/bin/python -m pip_audit --skip-editable 2>&1 | tail -20
```

Result: exit **1**:

```text
Found 7 known vulnerabilities in 2 packages
Name  Version ID              Fix Versions
----- ------- --------------- ------------
pip   25.3    PYSEC-2026-196  26.1.2
pip   25.3    PYSEC-2026-1796 26.0
pip   25.3    PYSEC-2026-196  26.1.2
pip   25.3    PYSEC-2026-2875 26.1
pip   25.3    PYSEC-2026-2876 26.1
pypdf 6.14.2  PYSEC-2026-3655 6.15.0
pypdf 6.14.2  PYSEC-2026-3656 6.15.0
```

The editable `harboriq` distribution was intentionally skipped by `--skip-editable`.

## Environment inventory

The Settings field names were extracted from `app/core/config.py` and compared directly with keys in `.env.example`. There are **17 code-used settings missing from `.env.example`**:

```text
LOCATION_PING_RATE_LIMIT_PER_WINDOW
LOCATION_PING_RATE_LIMIT_WINDOW_SECONDS
LOCATION_PING_MAX_PLAUSIBLE_SPEED_KMH
LOCATION_PING_PLAUSIBILITY_WINDOW_SECONDS
OFFLINE_QUEUE_MAX_AGE_SECONDS
OFFLINE_QUEUE_WARN_AGE_SECONDS
OFFLINE_QUEUE_FUTURE_SKEW_SECONDS
REDIS_URL
MFA_ENCRYPTION_KEY
BACKUP_S3_BUCKET
BACKUP_S3_PREFIX
REFRESH_COOKIE_NAME
AUTH_COOKIE_PATH
CSRF_COOKIE_NAME
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER
```

`.env.example` additionally documents `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID`; its own comments identify these as provisioning-script rather than FastAPI Settings values. A direct search found no additional `os.getenv`/`os.environ` reads in `app/`; Alembic's separate `alembic/env.py` reads `SERVICE_DATABASE_URL` / `DATABASE_URL`, both already represented.

## Security and tenant-isolation checks

- **Stripe webhook signature verification: PASS.** `app/api/v1/routes/stripe_webhooks.py` calls `stripe.Webhook.construct_event(raw, stripe_signature, settings.stripe_webhook_secret)` before parsing/side effects, rejects bad signatures with HTTP 400, and fails closed with HTTP 503 when the secret is unset outside development.
- **Tenant/RLS tests: PASS (focused scope).** The repository contains `test_auth_rls.py`, `test_crm_rls.py`, `test_invoicing_rls.py`, `test_rls_coverage.py`, and `test_rls_isolation.py`. Those files plus `test_stripe_webhook_signature.py` passed: **49 passed**.
- **Test collection caveat:** `tests/test_provisioning_scripts.py` has one collected skip because `boto3` is unavailable.

## TODO / FIXME / PLACEHOLDER / NotImplemented inspection

Exact case-sensitive scan:

```bash
cd /home/user/workspace/harboriq_repo && grep -RInE 'TODO|FIXME|PLACEHOLDER|NotImplemented' app/
```

Result: **3 matches**, all in `app/services/stripe_webhooks.py`; no `FIXME`, `PLACEHOLDER`, or `NotImplemented` match was found.

Notable item:

- `_on_subscription_payment_succeeded` handles Stripe Billing `invoice.payment_succeeded`, but is explicitly a TODO stub. It reads the amount/payment intent and queues a receipt; it does **not** resolve/update a local subscription by Stripe subscription ID. This risks inaccurate local SaaS subscription status for recurring Billing invoices.

## Findings by priority

| Priority | Problem | Launch impact / required disposition |
|---|---|---|
| **P0** | No clean full-suite result is available. The mandated test gate initially could not parse `--timeout=300` because its plugin was undeclared/uninstalled; after temporary installation, the `-x` run exceeded the 630-second execution limit without completing. | Do not approve production launch from this audit until CI or a suitable runner produces a clean full-suite result (and, if it fails, a non-`-x` total-failure count). |
| **P1** | `pip-audit` reports 7 known vulnerabilities: five for `pip 25.3` and two for `pypdf 6.14.2`; fixes are available. | Upgrade/rebuild the affected tooling dependencies, then re-run the audit. |
| **P1** | Stripe Billing recurring-payment handler is a TODO stub and does not update the local subscription record. | Complete and test subscription-state reconciliation before enabling/launching platform Stripe Billing. |
| **P2** | `.env.example` is missing 17 Settings values, including deployment-significant `REDIS_URL` and `MFA_ENCRYPTION_KEY`. | Bring the template and deployment documentation into parity with Settings; retain production-safe example values/comments. |
| **P2** | `pytest-timeout` is required by the documented launch command but missing from the dev dependency declaration. | Add it to the reproducible test/CI dependency set; this is the direct cause of the initial test-gate exit 4. |
| **P2** | One provisioning-script test is skipped when `boto3` is absent. | Decide whether AWS provisioning coverage belongs in the standard backend gate and declare/install its optional dependency accordingly. |
