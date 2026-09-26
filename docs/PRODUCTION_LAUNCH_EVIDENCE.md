# HarborIQ Production Launch Evidence Pack

Last updated: 2026-09-26

This record implements the six requested launch gates and captures what is verified now vs. what is blocked on external account access.

## 1) Domain/DNS recovery and Vercel verification

Status: **Blocked (account access required)**

Required evidence to attach:
- Cloudflare zone access confirmation for `harboriq.com`
- The two Vercel TXT verification records published exactly as issued
- Vercel domain verification status (apex + `www`)
- HTTPS certificate active
- Apex redirect behavior validated
- Reachability checks for apex and `www` (`curl` + browser)

Current repo/GitHub evidence:
- `docs/RELEASE_REGISTER.md` currently flags domain control as blocked on inaccessible Cloudflare account.

## 2) One Vercel remediation PR only

Status: **Partially complete (duplicate merges already happened)**

Requested target:
- Keep PR #92 as the single remediation candidate and close #94/#95 as duplicates.

Observed current state:
- PR #92: open (non-draft), branch `copilot/fix-github-actions-job-again`, head SHA `d8be8c297a6a8aafbf50a89bd3a642a362f5957d`
- PR #94: merged (closed)
- PR #95: merged (closed)

Evidence for content correctness:
- `vercel.json` is strict valid JSON and matches guarded SPA config (`tests/test_vercel_config.py`).
- CI success on PR #92 branch head SHA: run `36213074083` (workflow `CI`) concluded `success`.
- CI success on #95 branch head SHA: run `36169758615` concluded `success`.

Remediation required:
- Since #94 and #95 are already merged, do **not** merge additional duplicate fixes.
- Resolve with a single authoritative release SHA in gate 6 and document the duplicate-merge exception in release notes.

## 3) Secret incident cleanup

Status: **In progress / blocked on provider consoles**

Verified in repo:
- Current working tree has no leaked Render key string in tracked files.

Required external actions:
- Rotate exposed credentials (Render/Vercel/Stripe/SMTP/Twilio and any related integrations)
- Replace with hosted secrets (no plaintext in repo)
- Confirm post-rotation deploy and integration health

History cleanup requirement:
- The leaked key was previously committed and must be treated as compromised even if removed from current files.
- If policy requires history rewrite, perform coordinated rewrite + force-push + downstream clone reset procedure.

## 4) Provision/verify core app host (API, worker, beat, static frontend)

Status: **Blocked (host operations required)**

Verified from repo:
- Deployment target/runbook exists for Render + Neon (`docs/DEPLOYMENT_RENDER.md`).
- Migration chain in this clone currently ends at revision `0025` (`alembic/versions/0025_app_role_readonly_global_tables.py`).
- Health/readiness endpoints are defined and documented (`/api/v1/healthz`, `/api/v1/readyz`).

Required evidence to attach:
- Deploy IDs for API/worker/static services
- Migration output showing `alembic upgrade head` applied
- Runtime health probe output
- Tenant isolation + RBAC test run outputs against production-like target

## 5) Commercial-release smoke flow

Status: **Blocked (live environment execution required)**

Available harness:
- `smoke_test.py` covers signup/login, customer/vessel/job, invoicing, send, and pay-link flow.

Required additional evidence:
- Estimate send/approve and invoice conversion in the target release
- Payment settlement + Stripe webhook confirmation IDs
- Email delivery proof
- Recovery/rollback validation output

## 6) Release-only-after-evidence gate

Status: **Not approved yet**

Release decision record (must be complete before go-live):
- CI pass: **PARTIAL** (PR branch CI evidence exists; final release SHA still pending)
- Domain verified: **FAIL/BLOCKED**
- Runtime health checks: **BLOCKED**
- Production migration state: **BLOCKED**
- Smoke test results: **BLOCKED**
- Backup/recovery test: **BLOCKED**
- Final approved release SHA: **PENDING**

Go-live decision: **NO-GO** until every gate is green with attached evidence.
