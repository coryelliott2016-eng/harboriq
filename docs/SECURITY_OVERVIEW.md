# HarborIQ Security Overview, Access Control, and Threat Model

Status: v0.2.0 (2026-09-22). Every control below is cited to the file that
implements it. Anything not implemented is listed under "Gaps" — nothing here
is aspirational. HarborIQ holds **no** SOC 2 / ISO 27001 / PCI DSS / HIPAA
certification or attestation.

## Security posture summary

| Area | Control in code | Where | Verified by |
|---|---|---|---|
| Tenant isolation | PostgreSQL row-level security, ENABLE + FORCE on every table with `company_id`; app connects as non-superuser `harboriq_app` (no BYPASSRLS); tenant set per transaction via `SET LOCAL app.current_company_id` | `alembic/sql/*.sql`, `app/db/tenant.py` | `tests/test_rls_coverage.py`, `tests/test_*_rls.py`, `tests/test_estimates.py::test_estimates_are_isolated_between_tenants` |
| Service role | `harboriq_service` (BYPASSRLS) used only for pre-tenant paths: webhooks, public/portal token resolution, lead capture, migrations, backups | `app/db/session.py`, `alembic/env.py` | `tests/test_rls_coverage.py` |
| Least privilege on platform tables | App role has zero privileges on webhook ledgers and `marketing_leads` (0022/0023); read-only on `subscription_plans`, none on `alembic_version` (0025) | `alembic/versions/0022*`, `0023*`, `0025*` | `tests/test_rls_coverage.py` |
| Passwords | Argon2id (`argon2-cffi`) | `app/core/security.py` | auth tests |
| Sessions | 15-minute JWT access tokens; 30-day rotating refresh tokens with reuse detection; server-side denylist on logout | `app/core/config.py`, `app/core/token_denylist.py`, `app/services/auth*.py` | `tests/test_auth*.py` |
| Cookie sessions | httpOnly cookies + double-submit CSRF token | `app/core/csrf.py` | CSRF tests |
| MFA | TOTP enrollment with hashed backup codes; MFA secrets encrypted at rest with Fernet | `app/core/crypto.py`, `mfa_backup_codes` table | MFA tests |
| Brute force | Per-account lockout after 5 failures for 15 minutes; Redis per-IP fixed-window rate limits on login and password reset | `app/core/config.py`, `app/core/rate_limit.py` | rate-limit tests |
| Authorization | Role dependencies (`require_roles`, `require_operations`, `require_admin`) on every staff route | `app/api/deps.py` | RBAC tests per module |
| Customer portal / public links | Random tokens stored only as hashes, scoped to one purpose/resource, expiring, single-use where it matters (estimate approval records IP, user agent, PDF version) | `app/services/public_tokens.py`, `app/services/portal.py` | `tests/test_public_tokens.py`, portal tests |
| Payments | Stripe-hosted payment surfaces; HarborIQ never receives card numbers. Webhooks verify Stripe signatures and are idempotent via `stripe_processed_events` | `app/services/stripe_*.py`, `app/api/v1/routes/webhooks.py` | `tests/test_stripe_webhook_signature.py`, `test_stripe_webhook_idempotency.py` |
| Uploads | Magic-byte file signature validation, size limits | `app/core/file_signatures.py` | attachment tests |
| HTTP headers | HSTS (non-dev), `CSP: default-src 'none'` on the API origin, `X-Frame-Options: DENY`, `Referrer-Policy`, `nosniff` | `app/api/middleware.py` | middleware tests |
| Audit trail | `audit_log` rows for authentication events, public-token (estimate approval) events, and the staff estimate lifecycle. Invoice/refund actions are not yet audit-logged (state is recorded on the invoice/payment rows) | `app/services/auth.py`, `app/services/public_tokens.py`, `app/services/estimates.py` | `tests/test_estimates.py` (asserts audit sequence) |
| Secrets | Config from environment only; app refuses to start in production with the placeholder JWT secret; `.env` git-ignored; CI secret scan (gitleaks) on every PR; GitHub secret scanning + push protection enabled 2026-09-22 | `app/core/config.py`, `.github/workflows/ci.yml` | CI `secret-scan` job |
| Supply chain | `pip-audit`/`npm audit` in CI; Dependabot alerts and security updates enabled 2026-09-22 | `.github/workflows/ci.yml` | CI |
| Release control | `master` protected by ruleset `protect-master` (PR required, 5 required status checks, no force-push, no deletion, no bypass actors) | GitHub ruleset id 23833728 | direct push rejected (see release report) |
| Feature gates | Crypto payments and asset tokenization default **off** and must stay off until legal review | `app/core/config.py` | config tests |

## Access-control matrix

Roles are defined in `app/db/models.py` (`UserRole`) and enforced in
`app/api/deps.py`. Every role is confined to its own company by RLS
regardless of the role check.

| Capability | owner | admin | office | technician | Customer (portal token) |
|---|---|---|---|---|---|
| Invite/manage users | yes | yes (non-owner) | no | no | no |
| Billing plan / Stripe Connect / dunning | yes | yes | no | no | no |
| Customers & vessels | create/edit/read | create/edit/read | create/edit/read | read (all company customers) | own records only (read) |
| Jobs: create, schedule, assign, dispatch suggestions | yes | yes | yes | no | no |
| Jobs: execute (status, time, photos, parts used) | yes | yes | — | assigned jobs | no |
| Estimates: create / send / convert to invoice | yes | yes | yes | **no** (403) | view + approve own via single-use link |
| Invoices: create / send / void / refund | yes | yes | yes | no | view + pay own via Stripe |
| Reports (A/R aging, P&L, cash flow) | yes | yes | yes | no | no |
| Read audit log | database access only — no API or UI yet | | | | |

## Threat model (STRIDE summary)

Assets: tenant customer/vessel data, invoices and payment state, staff
credentials, portal links, Stripe webhook integrity.

| Threat | Example | Mitigation | Residual risk |
|---|---|---|---|
| Spoofing | Credential stuffing on login | Argon2id, lockout, per-IP rate limit, optional TOTP MFA | MFA is optional, not enforced for owners; rate limiter fails **open** if Redis is down (logged) |
| Spoofing | Forged Stripe webhook | Signature verification with `STRIPE_WEBHOOK_SECRET`; idempotency ledger | Depends on secret hygiene |
| Tampering | Customer edits estimate amount before approving | Approval token bound to estimate id + PDF version; server recomputes totals; convert copies stored lines only | — |
| Tampering | Tenant A writes into tenant B | FORCE RLS + app-role connection; cross-tenant tests | Service-role code paths must set tenant explicitly (reviewed; covered by tests) |
| Repudiation | Customer disputes approving an estimate | Approval records timestamp, IP, user agent, PDF version; audit log | Not a qualified e-signature |
| Information disclosure | Portal link leaked | Hashed, scoped, expiring tokens; no enumeration | Anyone holding a live link can view that customer's portal until expiry |
| Denial of service | Login/reset flooding | Rate limits | No WAF/CDN in front of the API yet (not deployed) |
| Elevation of privilege | Technician prices work or reads financials | Role dependencies; tests assert 403 | — |

## Gaps (tracked, not hidden)

1. **No production API deployment exists yet**, so TLS, WAF, backups, and
   monitoring are documented procedures, not running services.
2. MFA is not mandatory for owner/admin accounts.
3. The Redis rate limiter fails open on Redis outage (availability over
   strictness); alert on `rate_limit.redis_unavailable_failing_open` logs.
4. OpenTelemetry tracing, Grafana, and Loki are **not** wired in code;
   observability today is structured JSON logs, request IDs, Sentry (opt-in
   via `SENTRY_DSN`), and a Prometheus `/metrics` endpoint.
5. Audit logging does not yet cover invoice send/void/refund, user-role changes via admin UI, or data exports; there is no audit-log viewer.
6. No third-party penetration test has been performed.
7. The security contact mailbox on the public site (`Cory@HarborIQ.com`)
   does not currently receive mail (no MX record). Use GitHub private
   vulnerability reporting until email is restored.
