# Changelog

All notable changes to HarborIQ. Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-09-22

### Added
- **Staff estimates workflow** (`/api/v1/estimates`): create estimates with
  labor (fractional hours × rate), parts and fees such as diagnostic or
  haul-out fees; per-line taxable flag and a tax rate; send to the customer
  portal with an emailed link; customer approval via the existing single-use
  link; convert an approved estimate into a draft invoice containing exactly
  the approved lines. Owner/admin/office only. Migration `0024`.
- Estimates panel on the Job detail page (create, send, convert) with
  loading, empty, success and error states.
- `scripts/generate_reference_docs.py` and generated `docs/API_REFERENCE.md`,
  `docs/api/openapi.json`, `docs/DATABASE_SCHEMA.md`.
- Documentation: architecture, six ADRs, security overview with access
  matrix and threat model, release register, known limitations, testing/QA
  plan, operations runbook, incident response, customer onboarding/support,
  sales one-pager, marketing site review.

### Fixed
- Signup Terms/Privacy links pointed at `harboriq.com`, which does not serve
  the site; now configurable via `VITE_MARKETING_SITE_URL` (defaults to the
  live Vercel site).
- `/api/v1/readyz` returned HTTP 200 when the database was unreachable and
  echoed the driver error; now 503 with a generic body, detail logged.
- Portal estimate badges used a non-existent `rejected` status; now match
  the backend (`declined`, `viewed`, `invoiced`).

### Security
- Migration `0025`: app database role is read-only on `subscription_plans`
  and has no access to `alembic_version` (regression test added).
- `SECURITY.md` replaced (was the GitHub template) with a real policy using
  GitHub private vulnerability reporting.
- Repository: `master` protected by ruleset `protect-master`; secret
  scanning, push protection, Dependabot alerts and security updates enabled.

### Upgrade / rollback
- Back up the database, then `alembic upgrade head` (0023 → 0025).
- Rollback: revert the release merge commit and redeploy the previous SHA;
  `alembic downgrade 0023` is supported but rounds fractional estimate
  quantities to whole units.

## [0.1.0]
- Initial pilot build: auth/MFA, multi-tenant RLS, CRM, jobs, dispatch,
  invoicing, Stripe billing/Connect, portal, messaging, inventory/POs,
  reports, marinas/slips, offline field app. See
  `docs/BUILD_COMPLETION_REPORT.md`.
