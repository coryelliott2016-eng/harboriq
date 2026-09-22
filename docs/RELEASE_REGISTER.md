# HarborIQ Live Completion Register — v0.2.0

Last updated: 2026-09-22. Owner key: **Eng** = execution team (this repo),
**Cory** = founder decision/account action required.

Status vocabulary (strict):

- **Live** — deployed, reachable, verified against the production URL.
- **Verified (not deployed)** — full workflow works end-to-end in automated
  tests against a real PostgreSQL/Redis, with validation, RBAC and tenant
  isolation; not yet reachable by customers because no production API host
  exists.
- **Partial** — some of the workflow exists; gaps named.
- **Not built** — no implementation. Not claimed anywhere.
- **Blocked** — needs Cory; exact action listed.

## Public marketing site

| Requirement | Current state | Evidence | Owner | Blocker | Acceptance criteria | Status |
|---|---|---|---|---|---|---|
| Site deployed and reachable | Vercel project `harbor-iq/harboriq` | https://harboriq-gamma.vercel.app returns 200; all hash routes render (home, pricing, demo, about, security, FAQ, privacy, terms, cookies, investors) | Eng | — | Every nav link renders real content | **Live** |
| Configured primary domain (harboriq.com) | Domain is on a Cloudflare account not visible to any connected credential; harboriq.com currently answers 401 from a different Vercel owner | DNS: NS `norah/tate.ns.cloudflare.com`; Vercel requires TXT verification | Cory | Access to the Cloudflare account holding the zone | harboriq.com and www serve this Vercel project with TLS | **Blocked** |
| Value prop, audience, capabilities, CTAs | Present | Live page text reviewed 2026-09-22 | Eng | — | Clear headline, audience, capability sections, CTA on each page | **Live** |
| Demo / lead capture | Form renders; `POST /api/leads` returns 503 (no `DATABASE_URL` in Vercel env) and the page shows "online requests are temporarily unavailable — call 941-210-1663" | `/api/health` 200, `/api/leads` POST 503 | Cory | Connect a Postgres (e.g. Neon) `DATABASE_URL` in the Vercel project | Test lead stored and retrievable via admin endpoint | **Blocked** (fails closed honestly) |
| Site assistant (`/api/chat`) | 503 without `ANTHROPIC_API_KEY` | endpoint probe | Cory | API key decision | Answers grounded in site copy only | **Blocked** (optional) |
| Contact email | Site lists `Cory@HarborIQ.com`; domain has no MX and SPF `-all`, so mail bounces | DNS lookup | Cory | Restore mailbox or change the address | Test email to the listed address is received | **Blocked** |
| SEO: title, description, OG, favicon, robots, sitemap | Present, but canonical/OG/sitemap point to harboriq.com (not serving the site); hash routing limits indexability | Page source | Eng + Cory | Domain | Canonical URLs resolve to the live site | **Partial** |
| Accuracy of claims | No certification claims (good). Needs correction: "AI-assisted dispatch" (dispatch is rule-based), Terms mention AI "maintenance suggestions" (not in product), "ABYC-certified" needs confirmation, public investor page shows SAFE terms | See `MARKETING_SITE_REVIEW.md` | Cory (copy approval + counsel) | Site source not in this repo/session | Every claim traceable to code or a document | **Partial** |

## SaaS application

| Feature | Current state | Evidence | Owner | Blocker | Acceptance criteria | Status |
|---|---|---|---|---|---|---|
| Auth, signup/onboarding, MFA, sessions | Signup creates company + owner; login, refresh rotation, lockout, TOTP MFA, password reset, invites | `tests/test_auth_*`, `test_mfa`, `test_password_reset` | Eng | — | Signup → login → MFA → invite teammate works; lockout after 5 failures | **Verified (not deployed)** |
| Multi-tenant orgs + roles | FORCE RLS on all tenant tables; 4 roles | `tests/test_rls_coverage.py`, `test_*_rls.py`, access matrix in `SECURITY_OVERVIEW.md` | Eng | — | Cross-tenant reads return 404; wrong role returns 403 | **Verified (not deployed)** |
| CRM: customers & vessels | CRUD, search | `test_crm_customers`, `test_crm_vessels` | Eng | — | Create/edit/list with validation | **Verified (not deployed)** |
| Service requests / jobs | Job state machine, line items, time clock, photos | `test_crm_jobs`, `test_crm_job_status`, `test_job_time_clock`, `test_job_attachments` | Eng | — | Legal transitions only; attachments type-checked | **Verified (not deployed)** |
| Technician workflow & dispatch | Rule-based scoring with explanation, dispatch board, offline field app | `test_dispatch_*`, frontend offline tests | Eng | — | Suggestions ranked with factor breakdown; human assigns | **Verified (not deployed)** — rule-based, not AI |
| **Estimates** (new in v0.2.0) | Staff create (labor hours × rate, parts, fees), send to portal, customer approves, convert to invoice | `tests/test_estimates.py` (10), `JobEstimates.test.tsx` (5) | Eng | — | Totals correct; technician 403; cross-tenant 404; convert only after approval; invoice = approved lines | **Verified (not deployed)** |
| Diagnostic fees | Modeled as a `fee` line (with "Add diagnostic fee" shortcut) | same | Eng | — | Fee appears on estimate and invoice | **Verified (not deployed)** |
| Labor tiers / rate cards | Each labor line carries its own rate; no saved tiers | code search: none | Eng | Product decision on tier model | Select a tier → rate auto-fills | **Not built** |
| Parts / inventory / POs | Inventory, vendors, POs, reorder suggestions | `test_inventory_*`, `test_purchase_orders` | Eng | — | Parts decrement stock on use | **Verified (not deployed)** |
| Invoices & payments | Create, send, PDF, public pay link, void, refund, dunning | `test_invoicing_*`, `test_refunds`, `test_dunning`, `test_stripe_*` | Eng | Live Stripe keys | Paid webhook marks invoice paid exactly once | **Verified (not deployed)**; live settlement untested |
| Stripe subscriptions | Plans + subscription webhooks | `test_stripe_subscription_billing.py` | Cory | Live Stripe account + keys | Real card subscribes and renews | **Blocked** (test mode only) |
| Customer portal & communications | Portal (invoices, estimates, messages), email via outbox, SMS code | `test_portal_*`, `test_sms_*` | Cory | SMTP credentials (emails are logged, not sent); Twilio for SMS | Customer receives email and can approve/pay | **Verified (not deployed)**; delivery blocked on SMTP |
| Reports & history | A/R aging, P&L, cash flow, CSV/PDF exports | `test_pnl_report`, `test_report_*` | Eng | — | Numbers reconcile to invoices/payments | **Verified (not deployed)** |
| Audit logs | Auth, estimate approval, estimate lifecycle | `audit_log`; `test_estimates.py` asserts sequence | Eng | — | All money and permission events logged; viewer | **Partial** (no invoice/refund audit rows, no viewer) |
| AI-assisted diagnostics | None | code search: no LLM/diagnostic module | Cory | Product + safety decision | Suggestions with source, confidence, human confirmation, fallback | **Not built** |
| Recall / service-bulletin intelligence | None | code search | Cory | Data source licensing decision | Match vessel/engine to bulletins | **Not built** |
| Mobile / PWA | PWA + Capacitor shell | `docs/mobile-launch-runbook.md` | Cory | Apple/Google developer accounts + signing | Signed build installs and syncs | **Partial** (PWA built; store release blocked) |
| Marina slips / storage billing | Slips, reservations, dry-stack, recurring billing | `test_slip_*` | Eng | — | — | **Verified (not deployed)** |
| Crypto payments / asset tokenization | Code present, **disabled by default** | `app/core/config.py` flags | Cory | Legal review | Stays off in production | **Deferred (off)** |
| Admin / empty / loading / error / permission states | Spinner, ErrorBanner, EmptyState components used across pages; 403s surface as errors | `frontend/src/components/ui.tsx`, page tests | Eng | — | Every data view has all four states | **Verified (not deployed)** |
| Production API + app hosting | Docker Compose deployment documented; no host provisioned | `docs/DEPLOYMENT.md` | Cory | Choose/pay for host + managed Postgres + Redis | `https://app.<domain>/api/v1/readyz` returns 200 | **Blocked** |

## Engineering, security, release controls

| Requirement | Current state | Evidence | Owner | Status |
|---|---|---|---|---|
| Protected `master` | Ruleset `protect-master` (id 23833728): PR required, 5 required checks, no force-push/deletion, no bypass | GitHub rulesets API; ADR 0006 | Eng | **Done** |
| CI green on release | lint, frontend, secret-scan, test, docker-build | PR #73 checks | Eng | See release report |
| Secret scanning + push protection | Enabled 2026-09-22 | repo `security_and_analysis` | Eng | **Done** |
| Dependabot alerts + security updates | Enabled 2026-09-22 | repo settings | Eng | **Done** |
| Private vulnerability reporting | Enabled 2026-09-22; SECURITY.md rewritten | `SECURITY.md` | Eng | **Done** |
| Dependency audit | `pip-audit` and `npm run audit:ci` gate CI | CI config | Eng | **Done** |
| Health checks | `/healthz`, `/readyz` (now 503 when DB down, no error leak) | `tests/test_health_readiness.py` | Eng | **Done** |
| Observability | JSON logs, request IDs, `/metrics`, Sentry opt-in | `ARCHITECTURE.md` | Eng | **Partial** (no OTel/Grafana/Loki; no host) |
| Backups & recovery | Scripts + restore rehearsal test; S3 run needs AWS bucket | `scripts/backup_db*.sh`, `test_backup_restore_rehearsal.py` | Cory | **Partial** |
| Docs set | Architecture, ADRs, API, schema, security, testing, ops, onboarding, sales, release notes, limitations | `docs/` | Eng | **Done** (this release) |
