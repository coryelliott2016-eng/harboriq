# HarborIQ Live Completion Register — v0.2.1

Last updated: 2026-10-18 (supersedes the v0.2.0 register of 2026-09-22; the
prior edition is preserved in git history). Owner key: **Eng** = execution
team (this repo), **Cory** = founder decision/account action required.

Status vocabulary (strict):

- **Live** — deployed, reachable, verified against the production URL.
- **Verified (not deployed)** — full workflow works end-to-end in automated
  tests against a real PostgreSQL/Redis, with validation, RBAC and tenant
  isolation; not yet reachable by customers because no production API host
  exists.
- **Partial** — some of the workflow exists; gaps named.
- **Not built** — no implementation. Not claimed anywhere.
- **Blocked** — needs Cory; exact action listed.

Business-segment status is tracked separately from shared feature status:

- **Ready** — required segment workflows and acceptance tests have evidence;
  limitations and marketing claims match that evidence.
- **Pilot-only** — an explicitly scoped pilot passed its acceptance tests, with
  remaining limitations recorded.
- **Incomplete** — coverage has not been fully audited or required workflows
  and tests are not complete.
- **Out of scope** — an explicit product decision excludes the segment.

## What changed since v0.2.0 (2026-09-22 → 2026-10-18)

| Item | v0.2.0 state | v0.2.1 state | Evidence |
|---|---|---|---|
| CI on `master` | Red since the PR #79 merge (frontend `audit-ci` gate) | **Green** (run [39186732922](https://github.com/coryelliott2016-eng/harboriq/actions/runs/39186732922)) | PR [#134](https://github.com/coryelliott2016-eng/harboriq/pull/134) pinned patched transitive deps + regression test |
| Audit trail | Auth + estimate events only; no viewer | Invoice send/void/refund and role/activation changes recorded; `GET /api/v1/audit-log` for owner/admin | PR [#136](https://github.com/coryelliott2016-eng/harboriq/pull/136), `tests/test_audit_log.py` |
| Proxy-header trust | uvicorn default (trust 127.0.0.1 only) — behind Render every request would share one rate-limit bucket | `FORWARDED_ALLOW_IPS="*"` + `--proxy-headers` in the image | PR #136, `Dockerfile`, [ADR 0007](adr/0007-trust-platform-proxy-headers.md) |
| Production database | Provisioned 2026-09-22 | Confirmed: Neon `harboriq-app-production`, branch `production`, `alembic_version = 0025`, 36 public tables, RLS enabled on 31, roles `harboriq_owner/app/service`; 0 tenants | Neon API read 2026-10-18 |
| Marketing copy accuracy | "AI dispatch" claims live; SAFE round terms still on the **live** investors page (repo had removed them but the deploy never shipped) | Repo fixed: dispatch described as explainable rule-based scoring; investor keywords neutralised; canonical/OG/sitemap/robots generated from `SITE_URL`; real path routing with legacy `#/` redirect; assistant widget hidden until a provider is configured | `harboriq-marketing-site` [PR #2](https://github.com/coryelliott2016-eng/harboriq-marketing-site/pull/2) merged to `main` (`f5cae03`, CI green); **deploy pending** (see below) |
| README | 168 KB phase log | 7 KB entry point; phase log moved verbatim to `docs/BUILD_LOG.md` | this PR |

## Public marketing site

| Requirement | Current state | Evidence | Owner | Blocker | Acceptance criteria | Status |
|---|---|---|---|---|---|---|
| Site deployed and reachable | Vercel project `harbor-iq/harboriq`; last Ready production deploy 2026-10-06 | https://harboriq-gamma.vercel.app → 200; `/api/health` ok; `/api/lead-status` available | Eng | — | Every nav link renders real content | **Live** (previous build) |
| **Live build carries the accuracy fixes** | Fixed in repo (dispatch wording, investor keywords, canonical/OG, path routing, assistant gating); build + type-check + 13 API tests + claim guard pass locally and in CI | `main` @ `f5cae03` (PR #2, checks `build` + `secret-scan` green) | Eng + Cory | Vercel CLI credential became invalid mid-deploy on 2026-10-18 (`vercel teams ls` → "token … is not valid"; deployment `harboriq-1kolx5hxh` state unknown); the Vercel project is CLI-deployed (no Git integration), so merging alone does not ship. Reconnect Vercel, then `vercel --prod` from `main` | Live `/investors` contains no round terms; `/pricing` resolves as a real path; canonical = live origin | **Pending deploy** |
| Configured primary domain (harboriq.com) | Zone on a Cloudflare account not reachable by any connected credential; `harboriq.com` answers **401** from a different Vercel owner; the connected Cloudflare connector rejects its key (`6103 Invalid format for X-Auth-Key`) | `curl -I https://harboriq.com` 2026-10-18 | Cory | Recover the Cloudflare account that holds the zone (Workers Builds for this repo run in account `0ef84bbe…` — start there); reconnect the Cloudflare connector with a valid Global API Key + email, or an API token | `harboriq.com` and `www` serve the Vercel project with TLS | **Blocked** |
| Value prop, audience, capabilities, CTAs | Present | Live page text reviewed 2026-10-18 | Eng | — | Clear headline, audience, capability sections, CTA on each page | **Live** |
| Demo / lead capture | Form stores leads in Neon `harboriq-marketing` (project active 2026-10-18); endpoint fails closed, dedupes, rate-limits, honeypot | `GET /api/lead-status` → `{"available":true}`; `GET /api/leads` without token → 401 | Cory | No notification path: leads are only visible in the token-gated `/team` dashboard | Cory is notified of each new lead | **Live** (capture) / **Partial** (notification) |
| Site assistant (`/api/chat`) | Returns "temporarily unavailable" without `ANTHROPIC_API_KEY`; widget now hidden unless `/api/health.assistant` is true | endpoint probe 2026-10-18 | Cory | API key decision | Answers grounded in site copy only | **Blocked** (optional; no dead button once deployed) |
| Contact email | Site lists `Cory@HarborIQ.com`; zone has no MX | DNS | Cory | Same Cloudflare recovery; then add mailbox (Google Workspace/Zoho) and MX/SPF/DKIM/DMARC | Test email to the listed address is received | **Blocked** |
| SEO: title, description, OG, favicon, robots, sitemap, canonical | Generated at build from `SITE_URL` (production var set to the live alias on 2026-10-18); 15 indexable path URLs; previews emit `noindex` | `vite.config.ts` `siteMetadataPlugin`; local build output | Eng | Deploy (above); flip `SITE_URL` to `https://harboriq.com` when the domain is live | Canonical URLs resolve 200 on the live site | **Pending deploy** |
| Accuracy of claims | No certification claims. Dispatch no longer described as AI; Terms §6 now says "rule-based dispatch scoring … website assistant (when enabled)". Still to confirm with Cory: "ABYC-certified" phrasing on the About page | `grep -ri "AI dispatch\|AI-assisted dispatch"` → 0 hits in repo | Cory (ABYC wording) | — | Every claim traceable to code or a document | **Partial** |

## SaaS application

| Feature | Current state | Evidence | Owner | Blocker | Acceptance criteria | Status |
|---|---|---|---|---|---|---|
| Auth, signup/onboarding, MFA, sessions | Signup creates company + owner; login, refresh rotation, lockout, TOTP MFA, password reset, invites, terms acceptance (PR #54) | `tests/test_auth_*`, `test_mfa`, `test_password_reset` | Eng | — | Signup → login → MFA → invite teammate works; lockout after 5 failures | **Verified (not deployed)** |
| Multi-tenant orgs + roles | FORCE RLS on all tenant tables; 4 roles (owner, admin, office, technician) | `tests/test_rls_coverage.py`, `test_*_rls.py`, access matrix in `SECURITY_OVERVIEW.md`; production DB shows RLS on 31/36 tables (remaining 5 are global tables) | Eng | — | Cross-tenant reads return 404; wrong role returns 403 | **Verified (not deployed)** |
| CRM: customers & vessels | CRUD, search | `test_crm_customers`, `test_crm_vessels` | Eng | — | Create/edit/list with validation | **Verified (not deployed)** |
| Service requests / jobs | Job state machine, line items, time clock, photos | `test_crm_jobs`, `test_crm_job_status`, `test_job_time_clock`, `test_job_attachments` | Eng | — | Legal transitions only; attachments type-checked | **Verified (not deployed)** |
| Technician workflow & dispatch | Rule-based scoring with explanation, dispatch board, offline field app | `test_dispatch_*`, frontend offline tests; [ADR 0003](adr/0003-rule-based-dispatch.md) | Eng | — | Suggestions ranked with factor breakdown; human assigns | **Verified (not deployed)** — rule-based, not AI |
| Estimates | Staff create (labor hours × rate, parts, fees), send to portal, customer approves, convert to invoice | `tests/test_estimates.py`, `JobEstimates.test.tsx` | Eng | — | Totals correct; technician 403; cross-tenant 404; convert only after approval | **Verified (not deployed)** |
| Diagnostic fees | Modeled as a `fee` line with shortcut | same | Eng | — | Fee appears on estimate and invoice | **Verified (not deployed)** |
| Labor tiers / rate cards | Each labor line carries its own rate; no saved tiers | code search: none | Eng | Product decision on tier model | Select a tier → rate auto-fills | **Not built** |
| Parts / inventory / POs | Inventory, vendors, POs, reorder suggestions | `test_inventory_*`, `test_purchase_orders` | Eng | — | Parts decrement stock on use | **Verified (not deployed)** |
| Invoices & payments | Create, send, PDF, public pay link, void, refund, dunning; **send/void/refund now audited** | `test_invoicing_*`, `test_refunds`, `test_dunning`, `test_stripe_*`, `test_audit_log` | Eng | Live Stripe keys | Paid webhook marks invoice paid exactly once | **Verified (not deployed)**; live settlement untested |
| Stripe subscriptions | Plans + subscription webhooks | `test_stripe_subscription_billing.py` | Cory | Live Stripe account + keys | Real card subscribes and renews | **Blocked** (test mode only) |
| Customer portal & communications | Portal (invoices, estimates, messages), email via outbox, SMS code | `test_portal_*`, `test_sms_*` | Cory | SMTP credentials (emails are logged, not sent); Twilio for SMS | Customer receives email and can approve/pay | **Verified (not deployed)**; delivery blocked on SMTP |
| Reports & history | A/R aging, P&L, cash flow, CSV/PDF exports | `test_pnl_report`, `test_report_*` | Eng | — | Numbers reconcile to invoices/payments | **Verified (not deployed)** |
| Audit logs | Auth, estimate lifecycle, **invoice send/void/refund, role change, de/re-activation**; owner/admin read API with cursor pagination and filters | `tests/test_audit_log.py` (11 cases), `app/services/audit.py` | Eng | — | All money and permission events logged; viewer | **Verified (not deployed)** — API only, no frontend viewer yet |
| AI-assisted diagnostics | None | code search: no LLM/diagnostic module | Cory | Product + safety decision | Suggestions with source, confidence, human confirmation, fallback | **Not built** (not marketed) |
| Recall / service-bulletin intelligence | None | code search | Cory | Data source licensing decision | Match vessel/engine to bulletins | **Not built** (not marketed) |
| Mobile / PWA | PWA + Capacitor shell (Capacitor 8.5.3 after #134) | `docs/mobile-launch-runbook.md` | Cory | Apple/Google developer accounts under HarborIQ, Inc. + signing | Signed build installs and syncs | **Partial** (PWA built; store release blocked) |
| Marina slips / storage billing | Slips, reservations, dry-stack, recurring billing | `test_slip_*` | Eng | — | — | **Verified (not deployed)** |
| Crypto payments / asset tokenization | Code present, **disabled by default** | `app/core/config.py` flags | Cory | Legal review | Stays off in production | **Deferred (off)** |
| Admin / empty / loading / error / permission states | Spinner, ErrorBanner, EmptyState components used across pages; 403s surface as errors | `frontend/src/components/ui.tsx`, page tests | Eng | — | Every data view has all four states | **Verified (not deployed)** |
| Production API + app hosting | Render blueprint complete (`render.yaml`: API, worker+beat, Key Value, env group; `preDeployCommand: alembic upgrade head`; `autoDeploy: false`); **no Render account connected** — credentials stored in Vercel are write-only ("sensitive") and cannot be read back by automation | `docs/DEPLOYMENT_RENDER.md`; Vercel env listing 2026-10-18 | Cory | Create/connect Render, sync the blueprint, fill `harboriq-shared` secrets (Neon URLs, `JWT_SECRET`, `MFA_ENCRYPTION_KEY`, Stripe), first deploy | `https://<api-host>/api/v1/readyz` → 200; signup → login → job → invoice in production | **Blocked** |

## Business-segment release states

This matrix is an audit register, not a feature claim. No segment-specific
implementation or readiness is inferred from shared CRM, scheduling, inventory,
billing, or permission features. Evidence and gaps must be filled during the
Phase 19 audit; until then every segment is **Incomplete**.

| Business segment | Required workflows | Existing implementation and evidence | Missing capability / audit gap | Acceptance test | Owner / blocker | Release status |
|---|---|---|---|---|---|---|
| Commercial fishing operators | Fleet/crew, trip planning, maintenance, operating expenses, catches/landings, buyer sales, settlements | Not yet audited by segment | Implementation and evidence unknown; audit data model, permissions, payment/settlement rules, and reporting | Record a trip with expenses and sales; produce reviewable trip profitability and crew settlement | Eng + Cory / Phase 19 audit | **Incomplete** |
| Bait and tackle shops | Retail checkout, live-bait and bulk/weight/unit inventory, purchasing/receiving, spoilage, replenishment, customer accounts | Not yet audited by segment | Implementation and evidence unknown; audit retail-specific stock and payment rules | Receive bait, sell a quantity, record loss, reconcile stock and sales | Eng + Cory / Phase 19 audit | **Incomplete** |
| Boat clubs | Memberships, reservations/availability, qualifications, check-out/in, damage, maintenance holds, recurring billing, usage limits | Not yet audited by segment | Implementation and evidence unknown; audit eligibility, conflict prevention, and recurring/usage billing | Eligible member reserves an available vessel, checks out/in, and receives correct charges without double booking | Eng + Cory / Phase 19 audit | **Incomplete** |
| Boat rental businesses | Agreements, availability, deposits, waivers, inspections, fuel/late charges, damage | Not yet audited by segment | Implementation and evidence unknown; audit end-to-end rental and final-billing rules | Complete reservation through return and final billing with an inspection trail | Eng + Cory / Phase 19 audit | **Incomplete** |
| Charter and fishing-guide businesses | Trips, passenger capacity, captain/crew assignment, deposits, cancellation, weather rescheduling, communications | Not yet audited by segment | Implementation and evidence unknown; audit capacity, crew scheduling, and payment-history preservation | Booking reserves vessel and crew, collects deposit, and reschedules without losing payment history | Eng + Cory / Phase 19 audit | **Incomplete** |
| Marinas and boat-storage operators | Occupancy, vessel assignments, recurring/transient charges, utilities, service requests | Existing slip/storage features are recorded below, but segment coverage is not verified | Audit occupancy, transient reservations, utilities, billing, permissions, and full workflow evidence | Assign vessel to a space without conflict and generate agreed charges | Eng + Cory / Phase 19 audit | **Incomplete** |
| Marine repair and mobile-service businesses | Estimates, work orders, dispatch, labor, parts, approvals, invoices, service history | Shared service features are recorded above; segment coverage is not verified | Audit the complete segment workflow, roles, payment rules, and acceptance evidence | Complete a service job from request through payment with accurate records and permissions | Eng + Cory / Phase 19 audit | **Incomplete** |

## Engineering, security, release controls

| Requirement | Current state | Evidence | Owner | Status |
|---|---|---|---|---|
| Protected `master` | Ruleset `protect-master` (id 23833728): PR required, 5 required checks (strict/up-to-date), thread resolution, no force-push/deletion, no bypass actors | GitHub rulesets API 2026-10-18; [ADR 0006](adr/0006-protected-master-ruleset.md) | Eng | **Done** |
| CI green on `master` | lint, secret-scan, test, frontend, docker-build all pass at `d4c9ef4` | run [39186732922](https://github.com/coryelliott2016-eng/harboriq/actions/runs/39186732922) | Eng | **Done** (was red 2026-10-05 → 2026-10-18) |
| Non-required check noise | "Workers Builds: harboriq" (Cloudflare account `0ef84bbe…`) fails on every PR; not required, but misleading | PR check lists | Cory | **Open** — disconnect the Workers Builds integration for this repo, or add a `wrangler` config if a Worker is intended |
| Secret scanning + push protection | Enabled | repo `security_and_analysis` | Eng | **Done** |
| Dependabot alerts + security updates | Enabled; four open Dependabot PRs (#129–#131, #133) are now redundant with #134 | PR list | Cory | **Open** — close the four redundant PRs |
| Dependency audit | `pip-audit` and `npm run audit:ci` gate CI | CI config | Eng | **Done** |
| Health checks | `/healthz`, `/readyz` (503 when DB down, no error leak) | `tests/test_health_readiness.py` | Eng | **Done** |
| Proxy-aware client IP | `FORWARDED_ALLOW_IPS="*"` + `--proxy-headers` | `Dockerfile`, ADR 0007 | Eng | **Done** (v0.2.1) |
| Observability | JSON logs, request IDs, `/metrics`, Sentry opt-in | `ARCHITECTURE.md` | Eng | **Partial** (no OTel/Grafana/Loki; no host to observe yet) |
| Backups & recovery | Scripts + restore rehearsal test; Neon automatic snapshot schedule **not available on the current plan** (API: "backup schedule creation is not enabled for this project"); S3 run needs AWS bucket | `scripts/backup_db*.sh`, `test_backup_restore_rehearsal.py`; Neon API 2026-10-18 | Cory | **Partial** — rely on Neon's plan restore window until a host runs `backup_db_s3.sh` nightly |
| Docs set | Architecture, ADRs (7), API, schema, security, testing, ops, onboarding, sales, release notes, limitations, build log | `docs/` | Eng | **Done** (this release) |

## Open pull requests (triage, 2026-10-18)

Twelve of the thirteen non-Dependabot open PRs are Copilot-agent proposals
(roadmaps, demos, AI Lab, Marine Signals, synthetic data). None has been
verified against the stage gates in the release report and none should be
merged on the strength of its description. Recommended handling is listed
in [`RELEASE_REPORT_v0.2.1.md`](RELEASE_REPORT_v0.2.1.md#open-pull-request-triage).
