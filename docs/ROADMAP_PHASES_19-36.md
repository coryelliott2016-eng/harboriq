# HarborIQ Roadmap — Phases 19–36

**Status:** Approved by Cory Elliott (founder), 2026-10-21
**Date:** 2026-10-21
**Baseline:** Phases 1–18 are the completed original build program, documented in [`COMPETITIVE_PARITY_ROADMAP.md`](COMPETITIVE_PARITY_ROADMAP.md) (Phase 18 = Crypto Payment Rail, shipped behind a default-off flag). Repository release v0.2.1.
**Supersedes:** The October 4 and October 5 phase proposals and any other forward-phase numbering. The asset-tokenization work formerly labeled "Phase 19" is now **Track X1** (see below).

## Status key

| Status | Meaning |
|---|---|
| Not started | No meaningful code or evidence exists |
| Partial (code) | Some code is merged, but the phase exit criterion is not met and nothing is verified in production |
| Blocked | Cannot proceed without an action from Cory |
| Complete | Exit criterion met, with evidence recorded in the release register |

No phase is marked Complete as of approval. Statuses are updated only with evidence in [`RELEASE_REGISTER.md`](RELEASE_REGISTER.md).

## Stage A — Prove it works and go live safely (Phases 19–22)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 19 | Release baseline and production stand-up | Factual completion register; production host live; launch blockers closed | Register signed off; API, workers and app running on Render against Neon; smoke tests pass; no known critical/high defects | **Blocked** — no Render account; harboriq.com Cloudflare zone not recovered | — |
| 20 | Tenant isolation and authorization | Every customer org sees only its own data; roles enforced on every object | Cross-tenant test suite passes for every core entity and API, including at the database (row-level security) layer | Partial (code) — row-level security rejects writes without tenant context; full suite not run | 19 |
| 21 | Authentication hardening | Secure sign-up, invites, password reset, MFA, lockout, session controls | Auth abuse-case tests pass; auth events written to audit log | Partial (code) — JWT secret placeholder rejected in production; role/activation changes audited (PR #136) | 19 |
| 22 | Release engineering and quality gates | Code reaches production only through passing, protected gates, with rehearsed rollback | Branch protection enforced (closes issue #115); all CI checks green on master, including the Workers build; rollback rehearsed once | Partial (code) — CI with test, lint, secret scan, frontend, Docker; Workers build failing; #115 open | 19 |

## Stage B — Finish the money loop (Phases 23–28)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 23 | Core service workflow | Customer → vessel → service request → work order → completion runs end to end | A real service job is run in the product with no spreadsheet workarounds | Partial (code) | 20, 21 |
| 24 | Technician field app | Mobile-first job execution: photos, checklists, time, signatures, offline sync recovery | A technician completes a job from a phone with intermittent signal; queued actions sync correctly | Partial (code) — encrypted offline cache, logout clearing, stale-action purge | 23 |
| 25 | Scheduling and dispatch | One dispatch board: capacity, assignment, reassignment, conflicts, ETAs | Dispatcher plans and changes a full day's work from one screen | Not verified | 23 |
| 26 | Estimates, diagnostic fees, labor tiers and invoicing | Estimates with diagnostic fees, labor tiers, parts, deposits, change orders, taxes and credits convert accurately to invoices | Approved estimate converts to a correct invoice; void/refund actions audited | Partial (code) — estimates create/send/convert (v0.2.0); invoice send/void/refund audited (PR #136) | 23 |
| 27 | Stripe payments and subscription billing | Customers pay invoices; shops pay HarborIQ subscriptions | Webhooks verified, idempotent, reconciled; refunds permission-gated; end-to-end test payment succeeds in test mode, then one live transaction | **Blocked** — live Stripe keys not configured | 26 |
| 28 | Customer portal and notifications | Customers approve work, book, pay and see history; reliable email/SMS/in-app notices with consent handling | A customer approves an estimate and pays without staff help; key events produce delivered, logged notifications | Partial — lead notifications test-fired; **Blocked** for company email (no MX record) | 26, 27 |

## Stage C — Marine depth (Phases 29–31)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 29 | Vessel, marina and slip operations | Full vessel lifecycle: profile, service history, slip/berth, storage, seasonal work | Staff manage a vessel's history and location from one record | Partial (code) | 23 |
| 30 | Parts, inventory and purchasing | Part usage, stock levels, reorder signals, vendor purchases, receiving, job costing | A used part decrements stock and shows up correctly in job profitability | Partial (code) | 26 |
| 31 | Reports, service history and audit logs | Owner dashboards: revenue, utilization, backlog, technician productivity, receivables, job margin; searchable audit log | Dashboard figures reconcile to transaction data; audit log is queryable by authorized admins only | Partial (code) — audit-log API (PR #136) | 26, 30 |

## Stage D — Intelligence and scale (Phases 32–34)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 32 | AI-assisted diagnostics and operating assistant (evidence-gated) | Grounded help: note summaries, message drafts, work-order enrichment, OEM-document retrieval | Permission-scoped, logged and reviewable; fails closed (no answer) when evidence is missing; safety-critical answers require cited sources; measured usefulness in pilot | Not started — **not to be marketed until exit criterion met.** Open proposals PRs #111, #122–#125 inform design | 31, pilot evidence |
| 33 | Integrations platform | Versioned public API, webhooks, accounting export, calendar/email, marine data feeds | API documented (OpenAPI); webhooks signed and validated; at least one production integration working | Partial (code) — OpenAPI generated by FastAPI | 22 |
| 34 | Reliability, observability and recovery | Structured logs, error tracking, uptime checks, backups, restore drill, incident runbooks | Monitoring live in production; Neon snapshots enabled; one restore drill and one simulated incident meet documented targets | Partial (code) — observability designed in; Neon auto-snapshots not enabled | 19 |

## Stage E — Commercial launch (Phases 35–36)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 35 | Security assurance readiness | Control library, access reviews, vulnerability management, penetration test, policy set | Independent penetration test done with criticals/highs fixed; NIST gap assessment complete. **No certification claimed** | Not started — readiness plan proposed | 20, 21, 34 |
| 36 | Commercial launch and customer success | Production site on harboriq.com, demo path, onboarding, pricing, legal pages, support, pilot conversion | First paid design-partner pilots onboarded, active, supported and measured against agreed success metrics | Partial — marketing site and lead capture live on harboriq-gamma.vercel.app; domain cutover blocked | 19–28, 34 |

## Critical path

19 → 20 + 21 + 22 → 23 → 26 → 27 → 28 → 36

The minimum sellable release is Phases 19–28 plus 34 and 36. Phases 29–33 and 35 can run in parallel once Phase 23 is stable.

## Cory's actions that unblock the plan

1. Recover the Cloudflare account that controls harboriq.com (Phase 19, 36).
2. Create or connect a Render account (Phase 19).
3. Add live Stripe keys after test-mode verification (Phase 27).
4. Set up MX records for Cory@HarborIQ.com (Phase 28).

## Out of scope for 19–36 (reassigned)

| Item | Where it was | Decision |
|---|---|---|
| Crypto Payment Rail — live enablement | Phase 18 (code complete, `CRYPTO_PAYMENTS_ENABLED=false`) | Stays Phase 18; turning it on in production is backlog after Phase 36 and needs legal review |
| Asset Tokenization Layer | Formerly labeled "Phase 19" (draft-only) | Renamed **Track X1**; stays off; backlog after Phase 36, needs securities-counsel review |
| Facility/network expansion, Marine Signals monitoring | Unmerged PR #118 (its own Phases 18–37), PR #116 | Their phase numbers are superseded; moved to the backlog; revisit after pilot evidence |
| Partner marketplace / service network | October 4 proposal | Moved to the backlog; gated on paid pilots |

## Rules for every phase

- A phase is Complete only when its exit criterion is met in production (or production-like staging) and the evidence is recorded in [`RELEASE_REGISTER.md`](RELEASE_REGISTER.md).
- Changing a phase's scope or order requires Cory's approval and an update to this file.
- Production deploys, DNS, billing, secrets and destructive database work require Cory's approval.
- No marketing claim for a capability until its phase is Complete.
