# HarborIQ Competitive Parity Roadmap

Goal: match the core capabilities of DockMaster (marine-specific incumbent,
40+ years, 1,000+ marinas/boatyards/dealers) and ServiceTitan (horizontal
field-service gold standard) — plus ship differentiators neither offers —
so HarborIQ is legitimately "top tier," not just MVP-viable.

Status as of Phase 8: auth, multi-tenant CRM, invoicing + Stripe Checkout
(single-account and, as of this phase, per-tenant Stripe Connect direct
charges), refunds, PDF/email invoice delivery, dunning, AR aging, React
frontend, a rule-based explainable AI dispatch engine, and production
deployment/observability hooks. 357 backend tests, 42 frontend tests, CI
green.

This document sequences everything still missing for parity, in priority
order for a mobile-marine-mechanic-first wedge strategy (see
`concepts/harboriq-deferred-items` in the project wiki for the raw backlog
this is organized from).

## Phase 8 — Payments & Billing Parity — **COMPLETE**
- [x] Stripe Connect (Standard accounts, direct-charge pattern) so each
      onboarded tenant is its own merchant of record; falls back to the
      single platform account until a tenant connects. Destination charges /
      `application_fee_amount` platform-fee revenue on top of Connect is
      explicitly deferred to a later phase (pricing/legal decision, not an
      architecture gap) — see the README's "Payment architecture" section.
- [x] Refunds and partial refunds, with a `refunds` audit table and
      `InvoiceSM` transitions to `refunded`/`partially_refunded`.
- [x] PDF invoice generation (reportlab) + real email delivery of the pay
      link, consuming the `invoice.send` outbox event that previously queued
      but was never read.
- [x] Automated dunning / overdue-invoice reminders against `due_date`, with
      a cooldown to avoid re-spamming; callable on demand or via a
      standalone script (no Celery beat/cron runner wired up yet).
- [x] Basic AR aging report (1-30/31-60/61-90/90+ day buckets), API +
      frontend page.

## Phase 9 — Customer Self-Service Portal
- Extend existing `public_tokens` pattern: customers view vessel/service
  history, approve estimates, pay invoices, and message the shop without
  a login — matching DockMaster Web's customer portal.

## Phase 10 — Team, Skills & Geocoding
- `PATCH /users` (self-service profile edits) — today a technician's
  `skills`/home coordinates can only be set by hand in the database.
- Team roster / list-users screen in the frontend.
- Geocoding integration for customer/company/technician addresses so the
  dispatch engine's distance factor has real data instead of degrading to
  neutral.

## Phase 11 — Live Dispatch Board + Map View
- Visual drag-and-drop dispatch board (calendar + map hybrid), replacing
  today's ranked-list UI — this is what makes "AI dispatch" feel real to a
  dispatcher, matching ServiceTitan's dispatch board.
- Opt-in live technician location.
- Two-way SMS (job confirmations, "on my way" texts).

## Phase 12 — Offline-Capable Mobile Field App
- The single most important gap for a mobile-mechanic-first wedge: an
  offline-first PWA/mobile app for technicians — job queue, photo/video/
  voice-note capture, digital signatures, time clock — works without
  signal in marinas/boatyards and syncs later, matching DockMaster Mobile.

## Phase 13 — Inventory, Parts & Vendor Integration
- Barcode/ticket scanning, purchase orders, low-stock auto-reorder, vendor
  catalog integration — and wires the dispatch engine's currently no-op
  parts-availability factor up to real data.

## Phase 14 — Accounting & Reporting
- Basic AR aging shipped in Phase 8; this phase covers the rest: a simple
  P&L/cash-flow view, exportable (CSV/PDF) reports including AR aging
  itself, and QuickBooks/Xero sync — pragmatically smarter than building a
  full GL from scratch to match DockMaster's accounting suite.

## Phase 15 — Marina/Slip Management (optional — different business model)
- Visual slip map, reservations, dry-stack scheduling, storage billing —
  DockMaster's core turf. Only worth building if HarborIQ intends to also
  serve fixed-location marinas, not just mobile mechanics — flagged for a
  go/no-go decision rather than assumed in scope.

## Phase 16 — Platform Hardening for Enterprise Scale
- Redis/Celery, MFA/TOTP, httpOnly-cookie refresh tokens, stateful token
  revocation, managed off-host backups, CDN/WAF, horizontal scaling —
  required before this can be marketed as enterprise-grade.

## Differentiators to preserve/lean into throughout (not incumbents' turf)
- Fully explainable AI dispatch scoring (factor-by-factor breakdown) vs.
  DockMaster's marketing-only "AI-powered scheduling" claim.
- Cloud-native architecture from day one vs. DockMaster's legacy desktop
  core synced to web.
- Purpose-built for independent/mobile marine mechanics — a segment
  neither DockMaster (fixed marinas) nor ServiceTitan (marine-agnostic)
  targets directly.
