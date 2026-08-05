# HarborIQ Competitive Parity Roadmap

Goal: match the core capabilities of DockMaster (marine-specific incumbent,
40+ years, 1,000+ marinas/boatyards/dealers) and ServiceTitan (horizontal
field-service gold standard) — plus ship differentiators neither offers —
so HarborIQ is legitimately "top tier," not just MVP-viable.

Status as of Phase 13: auth, multi-tenant CRM, invoicing + Stripe Checkout
(single-account and per-tenant Stripe Connect direct charges), refunds,
PDF/email invoice delivery, dunning, AR aging, a durable magic-link customer
self-service portal with customer<->staff messaging, self-service + admin
team profile editing with a team roster page, real OpenStreetMap Nominatim
geocoding for user and customer addresses (with a documented Google
Maps/Mapbox swap point) feeding the AI dispatch engine's distance factor,
React frontend, a rule-based explainable AI dispatch engine, production
deployment/observability hooks, a visual drag-and-drop dispatch board
with a live Leaflet/OpenStreetMap map and two-way SMS (console-fallback
graceful degradation until a real Twilio account is connected), an
installable offline-first PWA field app for technicians (job queue, offline
action queue with idempotent sync-on-reconnect, photo/signature capture,
time clock) installable on iPhone via Safari with no App Store account, and
now full inventory CRUD with per-tenant SKU/barcode-style lookup, vendors,
a draft/submit/receive purchase-order lifecycle with correctly guarded
`quantity_on_hand` writes, low-stock reorder suggestions with one-click
*draft* PO generation (a human still has to submit — deliberately not
unattended auto-reordering), and the AI dispatch engine's parts-availability
factor wired up to that real inventory data instead of its former permanent
no-op. 526 backend tests, 90 frontend tests, CI green.

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

## Phase 9 — Customer Self-Service Portal — **COMPLETE**
- [x] Extended the existing `public_tokens` pattern with a durable 90-day
      magic link (`purpose="portal"`) instead of a full customer
      login/password system: customers view their vessel/profile and job
      history, pay invoices and approve estimates via the SAME existing
      pay/approve flows (no duplicate logic), and exchange messages with
      the shop without a login — matching DockMaster Web's customer portal.
      New customer<->staff messaging (`messages` table) with a company-wide
      staff inbox, job-threaded view, and a "Send portal invite" action on
      the customer detail page. Real-time delivery (sockets/push) and a
      full customer password/account system remain explicitly deferred —
      see the README's "Customer self-service portal" and "Customer portal
      / messaging" sections.

## Phase 10 — Team, Skills & Geocoding — **COMPLETE**
- [x] `PATCH /users/{id}` (self-service profile edits) plus `GET /users`
      (team roster listing) — a technician (or an admin/owner on anyone's
      behalf, tenant-scoped) can now update `full_name`/`skills`/
      `address_text` without hand-editing the database; admins/owners can
      additionally change `role`/`is_active`, with self-edits always
      excluded from those two restricted fields to prevent accidental
      self-demotion.
- [x] Team roster / list-users screen in the frontend (`/team`, gated on
      `canManageOperations`) — table of teammates with role, skills,
      geocoded-address status, and an edit modal (self-edit vs.
      admin-editing-a-teammate render different field sets); the existing
      invite flow was preserved and folded into the same page.
- [x] Real geocoding integration (OpenStreetMap Nominatim — free, no API
      key, rate-limited to 1 req/sec, documented `SWAP POINT` for a future
      Google Maps/Mapbox provider in `app/services/geocoding.py`) wired
      into **user home addresses** and **customer addresses**: geocoding
      is attempted synchronously on save and failures never block the
      save (`latitude`/`longitude` stay `NULL` on no-match/timeout/blank
      address) so the dispatch engine's distance factor now has real data
      to score against instead of degrading to neutral for every match.
      A `POST /admin/geocode-backfill` route (+ CLI entry point) geocodes
      any pre-existing un-geocoded seed/legacy rows, is idempotent, and is
      re-runnable safely. **Company address geocoding is explicitly
      deferred** — no address field/route exists yet for `Company` — see
      the README's "Team, skills & geocoding" section for the full
      deferred list (company geocoding, a normalized `User` address field,
      the Google Maps/Mapbox swap itself, and a background/scheduled
      geocoding queue).

## Phase 11 — Live Dispatch Board + Map View — **COMPLETE**
- [x] Visual drag-and-drop dispatch board (`/dispatch`, one column per active
      technician plus an "Unassigned" column) as the primary day-to-day
      assignment surface — this is what makes "AI dispatch" feel real to a
      dispatcher, matching ServiceTitan's dispatch board. Dropping a job on
      a technician's column calls the SAME `POST /jobs/{id}/assign` endpoint
      the Phase 7 ranked-candidates list already used (`DispatchSuggestions`
      was left untouched) — one assignment code path, two UIs.
- [x] A live Leaflet/OpenStreetMap map (free, no API key) under the board,
      showing technician markers (live GPS ping vs. static geocoded
      home-base fallback) and job/customer markers (reusing Phase 10's
      geocoded `Customer.latitude`/`longitude`).
- [x] Opt-in, best-effort live technician location, POSTed from the browser's
      Geolocation API every few minutes while the staff web app is open —
      explicitly NOT background/mobile tracking; true background tracking
      is deferred to Phase 12 (the offline-capable mobile field app).
- [x] Two-way SMS: outbound job-confirmation and "on my way" texts via the
      outbox pattern, and an inbound Twilio-shaped webhook that lands
      customer replies in the SAME Phase 9 `messages` table/staff inbox,
      tagged `channel="sms"`. Mirrors `app/services/email.py`'s SMTP
      graceful-degradation exactly: no Twilio account is connected in this
      workspace, so every send logs to console/INFO instead of actually
      dispatching until `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/
      `TWILIO_FROM_NUMBER` are set — see the README's "Live dispatch board,
      map & SMS (Phase 11)" section for the full write-up and deferred
      items (per-tenant Twilio-number routing, true background tracking).

## Phase 12 — Offline-Capable Mobile Field App — **COMPLETE (PWA, not native)**
- [x] Installable PWA (`vite-plugin-pwa`: manifest + Workbox service worker,
      app-shell precached for offline load) with honest iPhone install
      instructions (Safari → Share → Add to Home Screen — no App Store
      account needed). A true native App Store/Play Store app is a
      **separate, user-initiated path** requiring the operator's own Apple
      Developer/Google Play accounts and was deliberately **not attempted**
      here — see the README's "Offline-first mobile field app (Phase 12)"
      section for the full rationale on why PWA-first is the right call for
      this wedge and what that trade-off costs versus native (no true
      OS-level background task, no push notifications without iOS 16.4+ and
      an already-installed PWA).
- [x] Dedicated technician field view (`/field`, `/field/:id`) — separate
      from the office `AppShell` — listing the signed-in technician's own
      upcoming jobs, backed by an IndexedDB job cache that falls back
      automatically (with an honest "showing cached data" indicator) when
      the network fetch fails.
- [x] Offline action queue (outbox pattern, client-side): clock-in/out and
      photo/signature attachments are written to IndexedDB first and
      replayed in order once connectivity returns, halting at the first
      failure so events can never be delivered out of order. Client-
      generated idempotency keys plus new backend unique partial indexes
      (migration `0011`, `job_attachments`/`job_time_entries`) make replay
      of an uncertain-outcome action safe to retry blindly — matching
      DockMaster Mobile/ServiceTitan/Jobber's baseline field-app capability
      of "works without signal in marinas/boatyards and syncs later."
- [x] Field capture wired through that same offline queue: photo capture
      (rear camera via `<input capture="environment">`), canvas-based
      digital signature (Pointer Events, no external library), and a time
      clock (clock in/out, with a one-open-entry-per-technician-per-job
      backend constraint).
- [ ] **Video/voice-note capture** — mentioned in this stub's original
      scope note, but the actual Phase 12 spec that was implemented called
      for photo + signature + time clock specifically, not richer media;
      deliberately not built. Would be a natural follow-up alongside the
      base64-in-Postgres → object-storage migration already staged via the
      unused `storage_path` column.
- [ ] **True background/mobile location tracking** from the field app —
      the PWA shell now exists to eventually host it, but Phase 11's
      foreground-tab-only `useLocationPing` was not wired into `/field`
      this phase. Still open.
- [ ] **Push notifications** — needs a VAPID keypair and a backend
      subscription/send path; not implemented this phase.

## Phase 13 — Inventory, Parts & Vendor Integration — **COMPLETE**
- [x] Full inventory CRUD (`app/services/inventory.py` extended alongside
      the pre-existing `FOR UPDATE`-guarded `use_inventory_part_atomic` —
      no second, competing writer of `quantity_on_hand` was introduced) plus
      a per-tenant partial-unique-index SKU constraint (migration `0012`)
      enabling `GET /inventory/lookup?sku=...`, a barcode-scan-or-type
      workflow. Frontend feature-detects the `BarcodeDetector` Web API and
      falls back to manual entry with an explicit caveat on Firefox/Safari,
      where that API is not supported — see the README's "Inventory, parts
      & vendors (Phase 13)" section for sourcing on that browser-support
      gap.
- [x] Vendors (`vendors` table + CRUD service/routes) with an optional
      `inventory_items.default_vendor_id` used to group reorder
      suggestions. No delete endpoint by design — same "deactivate by
      convention, never orphan a historical FK" pattern already used for
      customers/technicians elsewhere in this codebase.
- [x] Purchase orders: a `PurchaseOrderSM` state machine
      (`draft → {submitted, cancelled}`, `submitted → {received,
      cancelled}`, terminal states `received`/`cancelled`) mirroring
      `JobSM`/`InvoiceSM`. Receiving reuses the exact `FOR UPDATE`-guarded
      pattern the atomic part-decrement already established, just
      incrementing `quantity_on_hand` instead of decrementing it, and
      supports partial receipt per line item with a database-level CHECK
      (`quantity_received <= quantity_ordered`) plus an application-level
      422 guard against over-receiving in a single call.
- [x] Low-stock reorder suggestions (`GET /inventory/reorder-suggestions`,
      read-only) with one-click **draft** PO generation (`POST
      /inventory/reorder-suggestions/generate-po`) grouped by vendor. A
      human must still call `POST /purchase-orders/{id}/submit` before
      anything is committed to a vendor — **explicitly not** unattended
      background auto-ordering, a deliberate scope boundary documented in
      both the README and the route docstrings, not a gap.
- [x] AI dispatch engine's `parts_availability` factor (Phase 7's reserved,
      permanently-neutral weight) is now a real signal:
      `_compute_inventory_shortfall` sums a job's `part`-kind line items
      against current `quantity_on_hand` and the existing dispatch test
      suite was updated to assert the new real scoring behavior (a job
      with an out-of-stock required part now scores measurably lower) —
      an intentional planned change flagged in the test diffs, not a
      regression.
- [ ] **Unattended auto-reordering** — see the draft-PO-generation bullet
      above; deliberately out of scope this phase, a materially different
      (higher-trust, no-human-in-the-loop) feature from "suggest and let a
      human draft."
- [ ] **Client-side barcode decoding fallback for Firefox/Safari** (e.g. a
      WASM barcode-reading library) — not implemented; those browsers get
      manual SKU entry only, with the gap explicitly surfaced in the UI
      rather than silently degraded.
- [ ] **Multi-warehouse/multi-location inventory** — `quantity_on_hand`
      remains one number per item per company, consistent with the
      single-shop-location assumption made since Phase 1.
- [ ] **Vendor-side integration** (EDI, vendor catalog/pricing feeds,
      emailing the PO to the vendor) — a submitted PO is a fact the shop
      acts on manually; nothing is transmitted to the vendor automatically.
- [ ] **Vendor deletion/archival UI** — vendors can be created/updated only;
      no archived/inactive flag or delete route exists yet, matching the
      "deactivate by convention" decision above.

## Phase 14 — Accounting & Reporting — **COMPLETE**
- [x] Simple cash-basis P&L (`GET /reports/pnl`): revenue = succeeded
      `payments` minus `refunds` in-period (cash collected, not accrual-
      invoiced value); parts cost = received PO line items
      (`quantity_received * unit_cost`); labor cost = closed
      `job_time_entries` duration × the technician's new `users.hourly_rate`
      (migration `0013_accounting_reports`) — with an explicit
      `labor_cost_unavailable` flag plus a named `unrated_technicians` list
      whenever a technician with time entries has no rate set, so the figure
      is a visibly-flagged undercount, never a silent $0. Grouped by month
      plus a totals row.
- [x] Cash flow view (`GET /reports/cash-flow`): cash in (same
      succeeded-payments figure) vs. **cost incurred** (PO received line
      items) — deliberately not labeled "cash out," since the schema has no
      vendor-payment-date field; the API returns an explicit
      `cost_incurred_caveat` string and the frontend renders it directly
      rather than only documenting the accrual-vs-cash distinction in the
      README.
- [x] CSV exports for every report — `GET /reports/{ar-aging,pnl,
      cash-flow}/export.csv` — plus `GET /reports/transactions/export.csv`,
      a QuickBooks Online-importable 3-column journal (date, description,
      amount) covering collected revenue and incurred PO costs, so a
      bookkeeper can import into QuickBooks/Xero/any spreadsheet today
      without a live API integration.
- [x] Frontend `/reports` section: P&L tab (recharts bar chart + monthly
      table + unrated-technicians warning banner) and Cash Flow tab
      (recharts line chart + monthly table + the cost-incurred caveat),
      each with a date-range picker and CSV export button, plus an
      AR-aging export button added to the existing Phase 8 page and a
      page-level QuickBooks CSV export button. `recharts` added as the
      project's first charting dependency (none existed before this phase).
      Gated behind `canManageOperations`, same pattern as `ArAgingRoute`/
      `TeamRoute`.
- [ ] **Live QuickBooks/Xero OAuth sync** — deliberately out of scope per
      the phase spec: a real integration requires the user to separately
      register a developer app with Intuit Developer and/or Xero Developer
      under their own account (app-review process, chart-of-accounts
      mapping decisions only the shop's bookkeeper should make) — no such
      app is registered for this product. The CSV export bridge above is
      the pragmatic today-it-works alternative; see the README's "Future:
      live QuickBooks/Xero sync" section for exactly what that would
      require.
- [ ] **Full double-entry general ledger** — no chart of accounts, no
      journal postings, no balance sheet; reports are computed directly
      from operational tables (invoices, payments, refunds, POs, time
      entries), matching this phase's own "pragmatically smarter than a
      full GL" framing rather than a gap.
- [ ] **Accrual-basis P&L** — revenue is recognized on cash collection, not
      invoice issuance; an invoice sent one month and paid the next is next
      month's revenue in this report. Called out explicitly rather than
      silently assumed.
- [ ] **Vendor cash-payment-date tracking** — `purchase_orders` has no
      field for when the shop actually paid a vendor invoice, only
      `received_at`; cash flow reports "cost incurred," not "cash paid,"
      with that caveat surfaced in both the API response and the UI.
- [ ] **PDF report exports** — only CSV was built this phase; CSV is the
      format that directly serves the QuickBooks-import use case, the
      higher-value target for a bookkeeper-facing export.

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
