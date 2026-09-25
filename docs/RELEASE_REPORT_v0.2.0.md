# HarborIQ Release Report — v0.2.0

Date: 2026-09-22 · Release PR: [#73](https://github.com/coryelliott2016-eng/harboriq/pull/73) · Merge commit: `c7b136a`

## 1. Release verdict

**Not ready** for paid commercial SaaS customers — **Ready with named
limitations** for what is live today (the marketing site) and as a
CI-verified release of the application code.

- The application (API + web app) passes 779 backend tests and all frontend
  checks, but **no production host exists**, so customers cannot reach it.
- The marketing site is live and honest, but its primary domain, company
  email, and online lead capture each need an account action by Cory.

## 2. Production URLs and verified flows

| URL | Verified 2026-09-22 |
|---|---|
| https://harboriq-gamma.vercel.app | 200; all pages render (home, features, marinas, pricing, security, about, FAQ, release log, privacy, terms, cookies, investors, demo) |
| https://harboriq-gamma.vercel.app/api/health | 200 |
| `POST /api/leads` | Validates input (400 on invalid payload); valid submissions return 503 because no lead database is configured; page shows a phone CTA instead of a fake success |
| https://harboriq.com | 401 from a different owner; **not** serving this site |
| Application API / web app | **Not deployed** |

## 3. Feature completion

See [`RELEASE_REGISTER.md`](RELEASE_REGISTER.md) for the full table with
evidence and acceptance criteria. Summary:

| Status | Features |
|---|---|
| Verified in CI (not deployed) | Auth/MFA/onboarding, multi-tenant RLS + roles, CRM, jobs, dispatch (rule-based), **estimates → approval → invoice (new)**, diagnostic fees, parts/inventory/POs, invoices/payments/refunds/dunning, portal + messaging, reports, marinas/slips, offline PWA, empty/loading/error/permission states |
| Partial | Audit logging (no invoice/refund rows, no viewer), observability (no OTel/Grafana/Loki), backups (S3 run untested), mobile (unsigned), site SEO/claims |
| Not built (not claimed) | Labor rate tiers, AI-assisted diagnostics, recall/service-bulletin intelligence |
| Blocked on Cory | Production host, domain, email, lead DB, SMTP, live Stripe, store signing |

## 4. Changes made today

Repository (all via PR #73, merged after 5/5 required checks):

- `9fa0059` feat(estimates): staff create/send/convert workflow; migration 0024; 10 tests.
- `131951c` feat(web): Estimates panel on Job detail; portal status labels fixed; 5 tests.
- `40cadb2` fix(web): signup Terms/Privacy links pointed at non-serving harboriq.com.
- `eaff637` fix(api): `/readyz` now 503 when DB is down and no longer leaks driver errors.
- `62a8d39` fix(db): migration 0025 — app role read-only on `subscription_plans`, no access to `alembic_version`.
- `61d5ef3`, `81f55b3`, `8c3560b` docs: SECURITY.md, security overview/threat model/access matrix, architecture + diagrams, 6 ADRs, generated API/OpenAPI/schema reference, release register, known limitations, changelog, product overview, QA plan, ops runbook, incident response, onboarding/support, sales one-pager, marketing site review; version 0.2.0.

GitHub configuration:

- Ruleset `protect-master` (id 23833728): PR required, required checks `secret-scan`, `lint`, `test`, `frontend`, `docker-build` (strict), no force-push/deletion, no bypass. **Verified:** a direct push to `master` was rejected with `GH013: Repository rule violations`.
- Enabled: private vulnerability reporting, secret scanning, push protection, Dependabot alerts, Dependabot security updates.
- Closed 10 superseded master-push audit issues (#59–#65, #67, #71, #72) with evidence.

Deployments: none changed. The Vercel API is unreachable from the release
environment (TLS "certificate signature failure"), so no Vercel env or
domain changes were possible.

## 5. Tests and release controls

| Check | Result |
|---|---|
| Backend full suite (CI, real Postgres + Redis) | **779 passed**, 0 failed (7 min 40 s) |
| `pip-audit` | No known vulnerabilities |
| Frontend lint, type-check, build, Vitest, `audit:ci` | Pass |
| Secret scan (gitleaks) | Pass |
| Docker image build | Pass |
| Migrations 0024/0025 | Upgrade → downgrade → upgrade tested locally |
| Critical/high vulnerabilities known in code | None open |
| Medium/low | Tracked in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) (L7–L25) |

Rollback: revert merge `c7b136a` via PR, redeploy the previous tag; `alembic
downgrade 0023` supported (lossy for fractional estimate quantities).

## 6. Blockers requiring Cory

1. **Production host decision** — choose and pay for a host with managed
   Postgres + Redis (any Docker-capable VM works with `docs/DEPLOYMENT.md`).
2. **harboriq.com DNS** — log in to the Cloudflare account that holds the
   `harboriq.com` zone (nameservers `norah`/`tate.ns.cloudflare.com`) and add
   TXT `_vercel.harboriq.com` = `vc-domain-verify=harboriq.com,e60b0305ed903398f482`
   and `vc-domain-verify=www.harboriq.com,1bf6a985981dfaa86b67`, then attach
   the domains in Vercel → `harbor-iq/harboriq` → Settings → Domains.
3. **Company email** — restore MX/SPF/DKIM for `Cory@HarborIQ.com` (currently no MX; SPF `v=spf1 -all`).
4. **Lead capture** — add a Postgres `DATABASE_URL` in Vercel → project `harboriq` → Settings → Environment Variables, redeploy.
5. **SMTP and live Stripe** credentials for the app once hosted.
6. **Copy and legal approvals** — "AI dispatch" wording, ABYC claim, and the public SAFE terms on `/investors` (securities counsel).
7. **Vercel connector** — reconnect so the execution team can set env vars and domains.

## 7. Next three highest-value actions

1. Provision the production host and deploy v0.2.0 behind TLS; run the
   smoke test in `TESTING_QA_PLAN.md` with SMTP and Stripe test mode.
2. Recover `harboriq.com` DNS + email and turn on lead capture, so the live
   site can actually convert visitors.
3. Apply the marketing-site accuracy fixes (S1–S7) and move the site source
   into a repository with CI.
