# HarborIQ Product Overview & Requirements (v0.2.0)

## Vision
Give independent marine-service businesses — mobile mechanics, service
yards, and marinas — one operating system for the work they already do:
from the first call about a boat to a paid invoice, with records that follow
the vessel.

## Problem
Small marine shops run on texts, paper work orders, and generic
field-service or accounting tools that do not model vessels, engines, haul-
outs, slips, or offline work on the water. Quoting, approvals, and billing
leak time and money.

## Users and roles
| Persona | Role in app | Primary jobs |
|---|---|---|
| Shop owner | owner | Money, team, settings, approvals |
| Service manager | admin | Scheduling, dispatch, pricing |
| Front desk | office | Customers, estimates, invoices, payments |
| Technician | technician | Assigned jobs, time, photos, parts used — no pricing |
| Boat owner | portal (token) | See vessels/jobs, approve estimates, pay invoices, message the shop |

## Core requirements and v0.2.0 status
Authoritative per-feature status, evidence, and acceptance criteria live in
[`RELEASE_REGISTER.md`](RELEASE_REGISTER.md). Summary:

| Requirement | Status |
|---|---|
| R1 Multi-tenant accounts, roles, MFA | Verified (not deployed) |
| R2 Customers & vessels | Verified (not deployed) |
| R3 Work orders with state machine, labor/parts/fees, time, photos | Verified (not deployed) |
| R4 Estimates with approval and conversion to invoice | Verified (not deployed) — new in v0.2.0 |
| R5 Invoices, online payment, refunds, dunning | Verified (not deployed); live Stripe untested |
| R6 Explainable dispatch suggestions | Verified (not deployed); rule-based |
| R7 Offline field app (PWA) | Verified (not deployed) |
| R8 Customer portal & messaging | Verified (not deployed); email delivery needs SMTP |
| R9 Inventory, vendors, POs | Verified (not deployed) |
| R10 Marina slips & storage billing | Verified (not deployed) |
| R11 Reports & exports | Verified (not deployed) |
| R12 Labor rate tiers | Not built |
| R13 AI-assisted diagnostics (with safe fallbacks) | Not built |
| R14 Recall / service-bulletin intelligence | Not built |
| R15 Native mobile store apps | Partial (unsigned) |

## Non-goals for the pilot
Multi-region hosting, Kubernetes, crypto payments or asset tokenization
(code exists, disabled pending legal review), and ML-based dispatch.

## Success metrics for the pilot (to be measured, none reported yet)
- Time from job creation to estimate sent.
- Share of estimates approved online vs. by phone.
- Days sales outstanding (from A/R aging).
- Weekly active technicians per shop.

## Open product decisions (Cory)
1. Labor tier model: per-shop rate card vs. per-technician vs. per-job-type.
2. Whether and how to add AI diagnostics: data sources, liability language,
   human-confirmation UX, fallback when the model is unavailable.
3. Recall/bulletin data source (manufacturer feeds, USCG recalls) and licensing.

## October ecosystem increment: Service + Marina first

The operating core remains the existing tenant application: Service uses
customers, vessels, work orders, estimates and invoices; Marina uses slips,
reservations and the same billing pipeline. No new tenant customer database
or separate vertical operating system is introduced.

| Capability | Implementation boundary |
|---|---|
| Public Intelligence Lab | `/intelligence-lab`, independently accessed without a tenant login; disabled server-side by default |
| Marine information assistance | Bounded NOAA CO-OPS observations with source links, observed/retrieved timestamps and verification warnings; deterministic summaries, not an LLM |
| Pilot/contact request | Existing platform lead table; required contact authorization, separately optional marketing opt-in, server-recorded evidence |
| Rights-aware internal benchmarks | `app/services/data_rights.py`: trusted per-record rights metadata, retention/purpose/consent checks, fixed operational metrics and per-cohort suppression |
| Referrals | Recipient-specific authorization eligibility gate only; no marketplace, automatic introductions, or fees |
| Commercial Insights | Not launched; no analytics export endpoint or customer-data resale |
| USCG notices, Garmin/Navionics, NMEA/OEM feeds | Proposed; ingestion remains unimplemented pending source/access/licensing review |
| Generative AI, technical diagnostics, predictive ML | Not implemented by this increment; require separate safety evaluation and approved knowledge sources |

### Rights and disclosure invariants

Future ingestion must attach source, owner, tenant, collection/retention dates,
permitted and prohibited purposes, consent status/version, and applicable
license references. Unknown rights deny use. Contact and marketing consent
do **not** authorize referrals, model training, or analytics. The lead table
records contact/marketing evidence only; it is not an analytics input.

The internal rights gate accepts minimized operational events only, with no
free-text, customer or coordinate fields. Benchmarks require at least five
distinct businesses **and** five distinct owners in each metric cohort.
Fishing grounds, vessel movements, restricted AIS, confidential records,
licensed charts and feed data do not enter these benchmarks. This floor is
not an anonymization guarantee. No production extraction or persistent rights
registry is wired to tenant tables yet: before adding one, enforce these
checks at ingestion and retrieval using trusted server-side metadata, not
client-supplied permissions. Repeated-release/differencing review, lawful
basis, license review and disclosure approval are prerequisites to publication.

### Supervised pilot acceptance

Recruit consenting Service and Marina businesses through owner-led outreach;
no pilots or customer outcomes are asserted here. Use staging/test payment
data until production and payment gates pass.

Record these measurements in an access-controlled pilot record, not a public
analytics endpoint:

| Measure | Evidence to collect |
|---|---|
| Workflow completion | Attempted/completed Service estimate-to-invoice and Marina reservation-to-billing tasks, including failures |
| Information quality | Human comparison with NOAA source, source freshness, incorrect/uncertain responses and safe failures |
| Operating savings | Comparable before/after task duration and participant-confirmed changes; do not infer revenue savings |
| Demand | Participation, repeat usage and explicitly stated willingness to pay; distinguish interest from a paid commitment |
| Safety/privacy | Consent review, tenant isolation, expired-session denial, quota enforcement and sensitive-data exclusion |

The release gate is **not met merely by merging this code**. Require a
reachable tenant application, verified production domain/email/contact path,
one successful live NOAA observation with human source verification, a
clearly labeled demonstration, a consented lead stored and retrieved by the
platform administrator, and documented supervised pilot evidence.

### Partnership execution, not partnership claims

| Prospect / track | Next preparation | Completion evidence |
|---|---|---|
| Garmin/Navionics — commercial | Request Web API/Enhanced overlay terms; clarify storage, display and AI-use rights | Written license/access approval before any feed or chart integration |
| NMEA — standards | Request applicable licensing and certification guidance | Approved interoperability scope; no proprietary standards copied into AI retrieval |
| AMI and local marine operators — distribution | Prepare Service/Marina walkthrough and request supervised pilot introductions | Consent-based pilot agreement and named workflow/success criteria |
| BoatUS / Sea Tow — commercial | Prepare an opt-in referral proposition; distinguish business programs from data access | Written program terms and participant-specific referral authorization |
| NOAA — public data | Verify CO-OPS API operation, attribution, station/product compatibility and current terms | Dated source review and successful live adapter check; no endorsement claim |
| USCG NAVCEN — public information | Review publication format, freshness and permitted reuse before building notices adapter | Approved source inventory; no restricted AIS redistribution |
| USCG R&D / Mote — research | Prepare narrowly scoped public-notice discovery capability brief | Mutually approved research agreement, distinct from purchasing or public-data access |

These are prospects, not confirmed partners; no outreach was submitted by
this implementation. Commercial revenue pitches and public-benefit/research
pitches need separate agreements and success criteria. External licensed
integrations are not prerequisites for the initial Service/Marina pilot.
