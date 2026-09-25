# Phase 4 — Release verification (v0.2.1 candidate)

**Verified:** 2026-09-25 (UTC), branch `copilot/finish-publishing-harboraq`, base commit `8979899`
(= master head, whose push CI run 36084838084 is green).
Environment: Python 3.12.3, Node 22, PostgreSQL 16 + Redis 7 (containers), Docker 28.

Every gate below was executed in this session; results are the actual command
outcomes, not documentation claims.

## Gate results

| Gate | Command | Result |
|---|---|---|
| Backend tests (full suite) | `pytest -ra` against migrated Postgres 16 + Redis 7 | **PASS — 779/779** (512s); after the L25 change, all affected auth suites re-run: 69+2 new tests pass |
| Backend lint / SAST | `ruff check app tests scripts` | **PASS** — "All checks passed!" |
| Backend dependency audit | `pip-audit` (pip upgraded first, per CI) | **PASS** — no known vulnerabilities in resolvable dependencies |
| Frontend lint | `npm run lint` | **PASS** — 0 errors |
| Frontend type-check | `npx tsc --noEmit` | **PASS** |
| Frontend production build + PWA | `npm run build` | **PASS** — dist + `sw.js` generated (57 precache entries) |
| Frontend tests | `npm run test` | **PASS — 136/136** (33 files), re-run green after the L25 signup-body assertion was added to the existing submit test |
| Frontend dependency audit | `npx audit-ci --config audit-ci.jsonc`; `npm ci` | **PASS** — 0 vulnerabilities; only the reviewed allowlisted advisory |
| Clean-database migration | `alembic upgrade head` on fresh Postgres 16 + `00_roles.sql` | **PASS** — base → `0026` (head) |
| Upgrade + rollback rehearsal | `alembic upgrade head` → `downgrade -1` → `upgrade head` | **PASS** — 0026 applied, rolled back, re-applied cleanly |
| Production container builds | `docker build` (API Dockerfile, frontend Dockerfile) | **PASS** — both images build from scratch |
| Production container smoke test | run `harboriq-api:rc` against Postgres/Redis | **PASS** — `/api/v1/healthz` → `{"status":"ok"}`, `/api/v1/readyz` → `{"status":"ready","db":"ok"}` |
| Signup consent enforcement (live) | `POST /api/v1/auth/signup` in the prod container | **PASS** — 201 with `agreed_to_terms: true`; **422** when omitted |
| Tenant isolation / RLS | `tests/test_rls_coverage.py`, `test_*_rls.py` (part of full suite) | **PASS** — cross-tenant negative tests green |
| Backup/restore rehearsal | `tests/test_backup_restore_rehearsal.py` (part of full suite, uses `REHEARSAL_ADMIN_URL` scratch DB) | **PASS** |
| Secret scan | gitleaks gates CI (`secret-scan` job); `runtime` secret scan on changed files before commit | **PASS** |

## Changes made in this verification cycle

- **L25 closed** — Terms/Privacy consent is now an API-contract requirement
  (`agreed_to_terms: Literal[True]` in `SignupRequest`), recorded server-side
  with the database clock in `users.terms_accepted_at` (migration `0026`), and
  stamped into the `company.signup` audit-log metadata. Frontend sends
  `agreed_to_terms: true` and the checkbox continues to gate submission.
- Reference docs (`DATABASE_SCHEMA.md`, `docs/api/openapi.json`) regenerated
  at revision 0026.

## Gates NOT executable from this environment (unchanged from the register)

These require accounts/credentials that are intentionally absent here and are
tracked in `KNOWN_LIMITATIONS.md` / `RELEASE_REGISTER.md`:

- Production deploy (Render connect + `render.yaml` apply) — L1
- Primary domain + TLS on harboriq.com (Cloudflare account) — L2
- Company mailbox / SMTP relay — L3/L5
- Stripe **live-mode** settlement (test-mode webhooks/refunds are covered by
  the backend suite) — L6
- Signed Android/iOS store builds (developer accounts + certificates) — L17
- Third-party penetration test — L24

Branch protection gate **H-6**: the `protect-master` ruleset is recorded as
active in the release register; the master-push audit workflow remains in
place as an interim detective control and must be kept until organization-plan
constraints are re-checked.
