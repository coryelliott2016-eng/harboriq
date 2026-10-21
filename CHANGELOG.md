# Changelog

All notable changes to HarborIQ. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `docs/ROADMAP_PHASES_19-36.md` — founder-approved forward roadmap (Phases 19–36)
  with exit criteria, current status, dependencies and critical path.

### Changed
- Phase numbering de-conflicted: the draft-only asset-tokenization layer formerly
  labeled "Phase 19" is now **Track X1** across docs, code comments and test
  docstrings (no behavior change). Phase 18 (Crypto Payment Rail) is unchanged.
- `frontend/src/App.tsx` comment no longer uses a stray "Phase 22" label.

## [0.2.1] — 2026-10-18

Release verdict: **Not ready for paid production** (no production API host; see
`docs/RELEASE_REPORT_v0.2.1.md`). The code is verified; the hosting, domain and
payment accounts are founder actions.

### Added
- Audit trail for money and privilege events: `invoice.sent`, `invoice.voided`,
  `invoice.refunded`, `user.role_changed`, `user.deactivated`,
  `user.reactivated`, written in the same transaction as the change
  (`app/services/audit.py`).
- `GET /api/v1/audit-log` (owner/admin): newest-first, keyset-paginated,
  filterable by action prefix, resource and actor. OpenAPI regenerated
  (142 operations).
- `docs/BUILD_LOG.md` — the historical phase-by-phase notes moved verbatim out
  of the README.
- ADR 0007 — trust platform proxy headers.

### Changed
- Container trusts `X-Forwarded-For/-Proto` from the platform proxy
  (`FORWARDED_ALLOW_IPS="*"`, `--proxy-headers`), so per-IP rate limits and
  audit IPs are per client rather than per proxy.
- README rewritten as a short, current entry point with an honest status table.
- Release register, known-limitations register and release report refreshed
  for 2026-10-18.

### Fixed
- `master` CI was red since 2026-10-05 (frontend `audit-ci` gate). Pinned
  patched transitive dependencies (`source-map-js`, `undici`,
  `brace-expansion`), bumped Capacitor to 8.5.3, added a regression test
  (PR #134).

### Marketing site (separate repo, pending deploy)
- Dispatch is described as explainable, rule-based scoring everywhere; no "AI
  dispatch" claims remain. Terms §6 corrected.
- Real path routing with client-side rewrite of legacy `/#/` links; canonical,
  Open Graph, sitemap and robots generated from `SITE_URL` per environment;
  previews are `noindex`.
- "Ask HarborIQ" widget renders only when `/api/health` reports a configured
  assistant provider.
- Investor command-palette keywords no longer reference round terms.

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
