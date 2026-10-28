# HarborIQ Release Report — v0.2.1

Date: 2026-10-18 · Prepared by the execution team for Cory Elliott ·
Supersedes [`RELEASE_REPORT_v0.2.0.md`](RELEASE_REPORT_v0.2.0.md) (2026-09-22).

## 1. Release verdict

**Not ready for paid production. Ready for a supervised design-partner pilot
the same day a production host is connected.**

Plainly: the application code is complete for its intended v0.2 scope and is
verified in CI against a real PostgreSQL and Redis on every pull request. What
is missing is not code — it is three founder-controlled accounts: a host for
the API (Render), the Cloudflare account that holds `harboriq.com`, and Stripe
live mode. Until the host exists, no customer can reach the product, so no
claim of "live" is made for the application.

| Surface | Verdict |
|---|---|
| Application code (API, web app, PWA) | **Verified, not deployed.** 809 Postgres-backed tests in CI; `master` green at `20183a9`. |
| Production database | **Live and empty.** Neon `harboriq-app-production`, schema `0025`, RLS roles, 0 tenants. |
| Production API host | **Blocked** on a Render account (blueprint ready). |
| Marketing site | **Live** at https://harboriq-gamma.vercel.app on the 2026-10-06 build; the accuracy/SEO build is merged to `main` and **pending deploy** (Vercel CLI credential expired; reconnect requested). |
| Custom domain + company email | **Blocked** on Cloudflare account recovery. |
| Payments (live mode) | **Blocked** on Stripe live keys; test mode verified. |

## 2. Production URLs and verified flows

| URL | Status 2026-10-18 | Verified |
|---|---|---|
| https://harboriq-gamma.vercel.app | 200 | Home, pricing, demo, about, security, FAQ, legal pages render (previous build). |
| https://harboriq-gamma.vercel.app/api/health | `{"ok":true,"service":"harboriq-marketing",…}` | Function runtime healthy in `iad1`. |
| https://harboriq-gamma.vercel.app/api/lead-status | `{"available":true}` | Lead storage (Neon `harboriq-marketing`) reachable. |
| https://harboriq-gamma.vercel.app/api/leads (no token) | 401 | Admin lead listing is token-gated. Lead rows were **not** read (PII; founder-only). |
| https://harboriq-gamma.vercel.app/api/chat | "temporarily unavailable" | No model key; widget is hidden in the pending build. |
| https://harboriq.com | 401 (Cloudflare → other Vercel owner) | Not under our control yet. |
| Application API | — | No host. |

Application workflows verified in CI (not on a public URL): signup → login →
MFA → invite; customer → vessel → job → line items → estimate → portal approval
→ invoice → public pay link → webhook paid → refund; dispatch suggestions;
inventory/PO; slips and recurring storage billing; reports; **audit trail for
money and privilege events** (new).

## 3. Feature completion table

Status vocabulary as in the [release register](RELEASE_REGISTER.md).

| Capability | Status | Evidence |
|---|---|---|
| Customer & vessel CRM | Verified (not deployed) | `tests/test_crm_customers.py`, `test_crm_vessels.py` |
| Service requests / jobs / time clock / photos | Verified (not deployed) | `test_crm_jobs.py`, `test_job_time_clock.py`, `test_job_attachments.py` |
| Technician workflow & dispatch | Verified (not deployed); rule-based, explainable | `test_dispatch_*.py`; ADR 0003 |
| Estimates, diagnostic fees | Verified (not deployed) | `test_estimates.py` |
| Labor tiers / rate cards | **Not built** | code search |
| Parts, inventory, vendors, POs | Verified (not deployed) | `test_inventory_*.py`, `test_purchase_orders.py` |
| Invoices, pay links, refunds, dunning | Verified (not deployed); live settlement untested | `test_invoicing_*.py`, `test_refunds.py`, `test_dunning.py` |
| Subscription billing (Stripe) | Blocked (test mode only) | `test_stripe_subscription_billing.py` |
| Customer portal & messaging | Verified (not deployed); delivery blocked on SMTP/Twilio | `test_portal_*.py`, `test_sms_*.py` |
| Reports & service history | Verified (not deployed) | `test_pnl_report.py`, `test_report_*.py` |
| Audit logs | **Verified (not deployed) — upgraded this release**: invoice send/void/refund, role change, de/re-activation, owner/admin read API | `tests/test_audit_log.py` (11), PR #136 |
| Multi-tenant orgs, roles, RLS | Verified (not deployed) | `test_rls_coverage.py`, production DB RLS on 31/36 tables |
| Auth & onboarding | Verified (not deployed) | `test_auth_*.py`, `test_mfa.py` |
| AI-assisted diagnostics | **Not built; not marketed** | — |
| Recall / bulletin intelligence | **Not built; not marketed** | — |
| Mobile / PWA | Partial (PWA built; store release blocked on publisher accounts) | `docs/mobile-launch-runbook.md` |
| Admin / empty / loading / error / 403 states | Verified (not deployed) | `frontend/src/components/ui.tsx`, page tests |

## 4. Changes made today

### Application repo (`coryelliott2016-eng/harboriq`)
| Change | Reference |
|---|---|
| `master` CI restored to green (frontend audit gate) | [PR #134](https://github.com/coryelliott2016-eng/harboriq/pull/134) → `d4c9ef4`; run [39186732922](https://github.com/coryelliott2016-eng/harboriq/actions/runs/39186732922) |
| Audit trail for money/privilege events + `GET /api/v1/audit-log`; proxy-header trust in the container; version 0.2.1; OpenAPI regenerated (142 ops) | [PR #136](https://github.com/coryelliott2016-eng/harboriq/pull/136) → `20183a9` (merged) |
| README rewritten; phase log moved to `docs/BUILD_LOG.md`; release register, known-limitations register, CHANGELOG, ADR 0007, this report; tag `v0.2.1` | branch `release/v0.2.1-docs` (PR linked from the tag) |

### Marketing repo (`coryelliott2016-eng/harboriq-marketing-site`)
| Change | Reference |
|---|---|
| Honest dispatch copy; real path routing with legacy-hash rewrite; canonical/OG/sitemap/robots generated from `SITE_URL`; assistant widget gated; investor keywords neutralised; CI `secret-scan` permission fix | [PR #2](https://github.com/coryelliott2016-eng/harboriq-marketing-site/pull/2) → `main` @ `f5cae03` (checks green). **Not yet deployed** — the Vercel project is CLI-deployed and the CLI credential expired. |
| Vercel production env var `SITE_URL=https://harboriq-gamma.vercel.app` | Vercel project `harbor-iq/harboriq` |

### Infrastructure reads (no changes)
Neon production DB inspected (schema, roles, RLS, row counts); Neon snapshot
schedule attempted — not available on the current plan; Vercel env **names**
listed (values never read; platform keys are write-only).

## 5. Test results and release controls

| Check | Result |
|---|---|
| `master` CI (`d4c9ef4`) | lint ✔ secret-scan ✔ test ✔ frontend ✔ docker-build ✔ |
| PR #136 CI (final run [39188447910](https://github.com/coryelliott2016-eng/harboriq/actions/runs/39188447910)) | **809 passed**, 0 failed (13m32s against Postgres 16 + Redis) · docker-build ✔ · frontend ✔ · lint ✔ · secret-scan ✔ → squash-merged as `20183a9` |
| Marketing PR #2 CI | build ✔ (tsc, api tsc, 13 API tests, vite build, claim guard, npm audit) · secret-scan ✔ |
| Branch protection | Ruleset `protect-master` active: PR required, 5 required checks (strict), thread resolution, no bypass |
| Secret scanning / push protection / Dependabot / private vulnerability reporting | Enabled |
| High/critical dependency findings | 0 after #134 |
| Pen test / certifications | None (not claimed) |

## 6. Blockers that need Cory (smallest action each)

| # | Blocker | Smallest action | Where |
|---|---|---|---|
| B1 | **No production host** | Create a Render account (or connect the existing one) → New → Blueprint → select `coryelliott2016-eng/harboriq` → fill the `harboriq-shared` env group (`DATABASE_URL`, `SERVICE_DATABASE_URL` from Neon; `JWT_SECRET`; `MFA_ENCRYPTION_KEY`; Stripe keys) → Apply. Or hand the team a scoped Render API key through the secure credential form and we run it. | https://dashboard.render.com/blueprints · `docs/DEPLOYMENT_RENDER.md` |
| B2 | **Vercel session expired** (deploy of the fixed site is pending) | Click the Vercel reconnect prompt in this conversation; we redeploy and verify `/investors`, `/pricing`, `/sitemap.xml`. Alternative: run `vercel --prod` from the site repo yourself. | this thread |
| B3 | **harboriq.com** | Recover the Cloudflare account holding the zone (the account `0ef84bbe721a5046f22d5c1d464b6cdc` runs Workers Builds for the repo — start there). Then reconnect the Cloudflare connector with the account email + Global API Key (current key is rejected: `6103 Invalid format for X-Auth-Key`). | https://dash.cloudflare.com |
| B4 | **Company email** | After B3: create a mailbox for `Cory@HarborIQ.com` (Google Workspace or Zoho) and publish MX/SPF/DKIM/DMARC. | — |
| B5 | **Stripe live mode** | After B1: add live keys to the env group; run one $1 invoice + refund; complete Connect onboarding dry run. | https://dashboard.stripe.com |
| B6 | **Email delivery** | After B1: pick SMTP/Resend/SES and set `SMTP_*` in the env group; also add the same provider key to the marketing project for lead notifications. | — |
| B7 | **Workers Builds noise** | Disconnect the "harboriq" Workers Builds Git integration (or add a `wrangler` config if intended). | Cloudflare dashboard → Workers → harboriq → Settings |
| B8 | **PR queue** | Close Dependabot PRs #129–#131 and #133 (superseded by #134); decide on PR #89 (Copilot skill). | GitHub |
| B9 | **Neon housekeeping** | Delete branch `verify-v0.2.1-2026-10-18` (`br-shy-tooth-augde6g0`) — created for verification, empty. | https://console.neon.tech |

## 7. Open pull request triage

| PR | Type | Recommendation |
|---|---|---|
| #129, #130, #131, #133 | Dependabot | Close — superseded by #134 |
| #112, #114 | CI/dependency fixes | Close — superseded by #134 |
| #89 | Copilot "principal engineering" skill + (now-merged) CI fix | Founder decision: the skill file defines agent autonomy and rollback rules; merge only if that governance is intended |
| #119 | Docs: Render/AWS backup preflight | Review; small and plausibly correct |
| #87, #88, #96, #97, #98, #102, #103, #106, #116 | Copilot proposals (roadmaps, demos, AI Lab, Marine Signals, synthetic data, adaptive forecasting) | Do not merge without stage-gate evidence; keep as reference or close |

## 8. Next three highest-value actions

1. **Connect Render and deploy** (B1). Everything else — design partners,
   payments, retention data — waits on this. Expected outcome: `readyz` 200
   and a first tenant the same day.
2. **Redeploy the marketing site and recover the domain** (B2, B3). Removes
   the last inaccurate public material (round terms on `/investors`) and
   unblocks canonical SEO, company email and Cloudflare Access.
3. **Recruit three design partners within 60 miles of Sarasota** (stage-gate
   experiment 2). Weekly usage pulled from the audit log is the first real
   product evidence; nothing in this report substitutes for it.

## 9. Known limitations

See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) (31 items, L26–L31 new this
release). Nothing in this report claims a certification, a customer, revenue or
an AI capability that does not exist.

## Sources

- GitHub Actions run 39186732922 — https://github.com/coryelliott2016-eng/harboriq/actions/runs/39186732922
- PR #134 — https://github.com/coryelliott2016-eng/harboriq/pull/134
- PR #136 — https://github.com/coryelliott2016-eng/harboriq/pull/136
- Marketing PR #2 — https://github.com/coryelliott2016-eng/harboriq-marketing-site/pull/2
- Uvicorn settings (proxy headers) — https://uvicorn.dev/settings/
- Render Blueprints — https://render.com/docs/infrastructure-as-code

## Change log vs. v0.2.0 report
- Verdict unchanged in substance (no host) but every blocker now has an exact action.
- CI red → green; audit coverage gap closed; proxy-header defect found and fixed.
- Marketing accuracy fixes moved from "needs Cory copy approval" to "committed, pending deploy".
- Production DB state, Vercel env names and Neon plan limits verified rather than assumed.
