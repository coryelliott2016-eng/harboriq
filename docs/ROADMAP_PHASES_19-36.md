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
| 19 | Release baseline and production stand-up | Factual completion register, including a separate business-segment coverage audit; production host live; launch blockers closed | Register signed off with a per-segment workflow, evidence, gap, owner, blocker, acceptance test, and release status; API, workers and app running on Render against Neon; smoke tests pass; no known critical/high defects | **Blocked** — no Render account; harboriq.com Cloudflare zone not recovered; segment audit not recorded | — |
| 20 | Tenant isolation and authorization | Every customer org sees only its own data; shared and segment-specific roles enforced on every object | Cross-tenant test suite passes for every core entity and API, including at the database (row-level security) layer; segment-specific role/access matrices cover, where applicable, crew, cashier, club member, captain, rental customer, marina staff, and service staff | Partial (code) — row-level security rejects writes without tenant context; full suite and segment-specific role coverage not verified | 19 |
| 21 | Authentication hardening | Secure sign-up, invites, password reset, MFA, lockout, session controls for staff and business-specific users | Auth abuse-case tests pass; auth events written to audit log; invitation, identity, and access flows for each in-scope segment are tested against its role matrix | Partial (code) — JWT secret placeholder rejected in production; role/activation changes audited (PR #136); segment-specific flows not verified | 19 |
| 22 | Release engineering and quality gates | Code reaches production only through passing, protected gates, with rehearsed rollback | Branch protection enforced (closes issue #115); all CI checks green on master, including the Workers build; rollback rehearsed once | Partial (code) — CI with test, lint, secret scan, frontend, Docker; Workers build failing; #115 open | 19 |

## Stage B — Finish the money loop (Phases 23–28)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 23 | Core service workflow and segment modules | Service jobs plus foundational workflows for each in-scope segment are established | Each segment's foundational workflow passes without relying on downstream phases; full coverage-matrix acceptance is deferred to segment release readiness. Shared service-job completion alone does not establish segment readiness | Partial (code); segment-specific workflows not verified | 20, 21 |
| 24 | Field and crew app | Mobile-first job or trip execution: photos, checklists, time, signatures, offline sync recovery, and applicable crew/inspection tasks | A technician or other in-scope field user completes their segment workflow on a phone with intermittent signal; queued actions sync correctly | Partial (code) — encrypted offline cache, logout clearing, stale-action purge; segment workflows not verified | 23 |
| 25 | Scheduling, dispatch and reservations | Capacity, assignments, availability, conflict prevention, ETAs, vessel reservations, and maintenance holds as required by each segment | Segment-specific bookings and holds cannot conflict; dispatcher or reservation staff can complete the required scheduling workflow | Not verified | 23 |
| 26 | Estimates, fees, charges and invoicing | Estimates, labor/parts, deposits, change orders, taxes, credits, and segment-specific charges convert accurately to invoices | Approved estimates and segment-specific charges produce correct, auditable invoices and refunds | Partial (code) — estimates create/send/convert (v0.2.0); invoice send/void/refund audited (PR #136); segment rules not verified | 23 |
| 27 | Stripe payments and subscription billing | Customer payments, recurring memberships, booking deposits, refunds, and crew settlements are evaluated separately where applicable | Webhooks verified, idempotent, reconciled; permissions and payment/settlement rules pass each segment's acceptance tests; end-to-end test payment succeeds in test mode, then one live transaction | **Blocked** — live Stripe keys not configured; segment-specific rules not verified | 26 |
| 28 | Customer, member and booking experience | Customers, members, and business clients complete the relevant approvals, reservations, purchases, payments, and history workflows; notifications honor consent | Each segment's external-user flow is tested with its own permissions and payment rules; key events produce delivered, logged notifications | Partial — lead notifications test-fired; **Blocked** for company email (no MX record); segment-specific journeys not verified | 26, 27 |

## Stage C — Marine depth (Phases 29–31)

| # | Phase | Primary outcome | Exit criterion | Current status | Depends on |
|---:|---|---|---|---|---|
| 29 | Vessel, fleet, marina and storage operations | Vessel lifecycle and segment-specific fleets, assignments, availability, occupancy, storage, maintenance holds, and trip records | Applicable fleet and space workflows prevent conflicting assignments and preserve service/operating history | Partial (code); segment-specific operations not verified | 23 |
| 30 | Parts, retail inventory and purchasing | Part usage, live-bait and retail stock, bulk/weight/unit sales, purchasing, receiving, spoilage, replenishment, and job costing | Each relevant stock movement reconciles to sales, losses, purchases, and job/trip use | Partial (code); segment-specific inventory rules not verified | 26 |
| 31 | Segment reporting, history and audit logs | Shared financial/operational reports plus segment-specific trip profitability, crew settlements, retail reconciliation, fleet usage, and service history | Each segment's reports reconcile to underlying transactions; audit log is queryable by authorized admins only | Partial (code) — audit-log API (PR #136); segment reports not verified | 26, 30 |

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
| 36 | Segment-specific commercial launch and customer success | Production site on harboriq.com, accurate segment-specific demos, onboarding, pricing, legal pages, support, and pilot conversion | First paid design-partner pilots onboarded, active, supported, and measured against agreed success metrics; each marketed segment is explicitly **Ready** in the release register, with limitations matching verified workflows | Partial — marketing site and lead capture live on harboriq-gamma.vercel.app; domain cutover blocked; segment readiness not established | 19–28, 34 |

## Business-segment coverage matrix

This is proposed scope for evaluation, not a claim that these modules exist.
Shared HarborIQ capabilities may support parts of a workflow, but do not count
as evidence that a segment is implemented or ready. Phase 19 records evidence,
gaps, owners, blockers, acceptance results, and a separate release status for
each segment in [`RELEASE_REGISTER.md`](RELEASE_REGISTER.md).

| Business segment | Workflows to evaluate | Required data | Permissions to define and test | Payment rules to define and test | Example acceptance test |
|---|---|---|---|---|---|
| Commercial fishing operators | Fleet and crew records, trip planning, maintenance, fuel/operating expenses, catch/landing records, buyer sales, crew settlements | Vessels, crew, trips, expenses, fuel, catch/landings, buyers, sales, settlement basis | Operator, captain, crew member, office/admin; restrict trip, settlement, and financial records by role and organization | Buyer sales, trip expenses, and crew settlement calculations/review; refunds or adjustments auditable | Record a trip, associate expenses and sales, and produce a reviewable trip-profitability and crew-settlement record |
| Bait and tackle shops | Retail checkout, live-bait stock, bulk/weight/unit sales, purchasing, receiving, spoilage, replenishment, customer accounts | Products/SKUs, units and weights, lots or stock counts as needed, vendors, receipts, losses, sales, customer accounts | Owner/manager, retail cashier, inventory staff; cashier sales access must not imply purchasing or admin access | Retail tenders, refunds/voids, customer-account balances, and sales reconciliation | Receive bait, sell a quantity, record loss, and reconcile remaining stock and sales |
| Boat clubs | Membership plans, vessel reservations/availability, qualifications, check-out/check-in, damage reporting, maintenance holds, recurring billing, usage limits | Members/plans, vessels, qualifications, reservations, usage, condition/damage, holds, billing and limits | Club admin/staff, member; validate eligibility and prevent member access to other members' records | Recurring dues, usage charges, failed payments, credits/refunds, and limits | An eligible member reserves an available vessel, checks it out/in, and receives correct charges without double booking |
| Boat rental businesses | Rental agreements, availability, deposits, waivers, inspections, fuel charges, late returns, damage handling | Customers, vessels, reservations, agreements/waivers, inspection records, fuel, return times, damages, charges | Rental staff, manager, renter; separate operational review from customer self-service | Deposits, balances, fuel/late/damage charges, cancellations, refunds | Complete a rental from reservation through return and final billing with an inspection trail |
| Charter and fishing-guide businesses | Trip bookings, passenger capacity, captain/crew assignment, deposits, cancellations, weather rescheduling, customer communications | Trips, vessels, passenger manifests/capacity, crew, bookings, weather changes, deposits, notices | Owner/dispatcher, captain/crew, customer; passenger data and trip edits limited by role | Booking deposits, balances, cancellation/refund terms, and payment history across rescheduling | A booking reserves the correct vessel and crew, collects the correct deposit, and can be rescheduled without losing payment history |
| Marinas and boat-storage operators | Slip/storage occupancy, vessel assignments, recurring charges, transient reservations, utility charges, service requests | Spaces, vessels, occupancy dates, reservation terms, utilities, recurring charges, service requests | Marina/storage staff, service staff, vessel owner/customer; control occupancy changes and billing actions | Recurring/transient charges, utilities, credits/refunds, and service invoices | Assign a vessel to a space without occupancy conflict and generate the agreed charges |
| Marine repair and mobile-service businesses | Estimates, work orders, dispatch, labor, parts, approvals, invoices, service history | Customers, vessels, jobs, estimates, parts, labor/time, approvals, invoices, service history | Owner/admin, office, technician/mobile worker, customer; enforce approval and financial boundaries | Deposits, invoice payments, change orders, refunds/credits, and subscriptions as applicable | Move a service job from request through payment with accurate records and permissions |

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
