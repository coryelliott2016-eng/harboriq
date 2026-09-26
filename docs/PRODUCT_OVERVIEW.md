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
