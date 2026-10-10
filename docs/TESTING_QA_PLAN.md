# HarborIQ Testing & QA Plan

Applies from v0.2.0. The documented `protect-master` ruleset gates merging to
`master` on required CI checks passing on an up-to-date branch. Its live
configuration must be updated to include `repo-integrity` and enforced
CODEOWNER review for acceptance tests (see
[ADR 0006](adr/0006-protected-master-ruleset.md)).

## Automated test layers

| Layer | What | Where | Runs in CI job |
|---|---|---|---|
| Lint / static | `ruff` (Python, incl. security rules), ESLint with `jsx-a11y`, TypeScript `tsc` | `pyproject.toml`, `frontend/eslint.config.*` | `lint`, `frontend` |
| Backend unit + integration | 85 pytest modules against real PostgreSQL + Redis (no DB mocks): money math, state machines, RLS, RBAC, webhooks, portal tokens, outbox, reports, backups | `tests/` | `test` |
| Migrations | `alembic upgrade head` on a fresh database before tests | `.github/workflows/ci.yml` | `test` |
| Frontend unit/component | 33 Vitest + Testing Library files (API mocked at `fetch`) | `frontend/src/**/*.test.tsx` | `frontend` |
| Build | Vite production build; Docker images for app and frontend | `Dockerfile`, `frontend/Dockerfile` | `frontend`, `docker-build` |
| Dependency security | `pip-audit`, `npm run audit:ci` (fail on known vulns unless a reviewed exception exists) | CI | `test`, `frontend` |
| Secret scanning | gitleaks on every push/PR; GitHub secret scanning + push protection | `.gitleaks.toml` | `secret-scan` |
| Repository integrity | Reject tracked bytecode and unexpected binaries; verify repository-local skill inventory hashes | `scripts/check_repo_integrity.py`, `.github/skills/manifest.json` | `repo-integrity` |
| Tenant isolation contract | Every `company_id` table has FORCE RLS + policy; app role has no access to service-only tables | `tests/test_rls_coverage.py` | `test` |
| Defect-oriented acceptance | Tenant isolation, payment overpayment, and server-owned estimate pricing | `tests/acceptance/` | `test` |
| Backup/restore | Restore rehearsal into a scratch DB | `tests/test_backup_restore_rehearsal.py`, `scripts/rehearse_backup_restore.sh` | `test` |

## Not yet automated (tracked in KNOWN_LIMITATIONS)

- Browser end-to-end tests (Playwright) — L15.
- Manual accessibility audit — L16.
- Live Stripe settlement — L6.
- Load/performance testing — not started; no production traffic yet.

## Acceptance checklist per feature (definition of done)

A feature is "complete" only when all hold:

1. Full workflow passes an API-level test against real Postgres.
2. Validation errors return 422 with a useful message; illegal state
   transitions return 409.
3. Wrong role returns 403; another tenant's resource returns 404.
4. Money is computed server-side with `Decimal` and asserted to the cent.
5. UI shows loading, empty, error, and permission-denied states, with a
   component test for the primary path.
6. Documentation (API reference regenerated, register updated).

## Release smoke test (run after every production deploy)

Once a production host exists (L1), run against the real URL:

1. `GET /api/v1/healthz` → 200; `GET /api/v1/readyz` → 200.
2. Sign up a throwaway company; log in; enable MFA; log out/in with TOTP.
3. Create customer (with a test email you control) → vessel → job.
4. Create an estimate with a labor line (1.5 h), a diagnostic fee and a
   part; send it; confirm the email arrives; approve from the portal link.
5. Convert to invoice; send; pay with a Stripe test card (test mode) or a
   real $1 charge (live mode) and confirm the invoice shows paid once.
6. Refund; confirm status and Stripe dashboard agree.
7. Confirm a second test company cannot see the first company's job URL.
8. Check logs for errors and `/metrics` for request counts.

## Local commands

```bash
# backend (needs Postgres + Redis; see README)
alembic upgrade head && pytest -q
ruff check app tests scripts
# frontend
cd frontend && npm ci && npm run lint && npm run build && npm test && npm run audit:ci
```
