# HarborIQ v2 — Working Repo Scaffold

Marine service operating system. Corrected implementation of the HarborIQ
build plan: every issue from the technical critique is fixed at the code level.

> **Status:** scaffold, real authentication, the CRM/operations core
> (customers, vessels, work orders), **invoicing + Stripe payment
> collection**, **Stripe Connect onboarding, refunds, PDF/email invoice
> delivery, dunning, and AR aging** (see "Billing operations" below), a
> **licensed-processor stablecoin/crypto invoice-payment rail** (no
> HarborIQ on-chain custody; see "Crypto payment rail" below), a
> **customer self-service portal + customer<->staff messaging** (see
> "Customer self-service portal" below), the
> **React frontend**, **deployment/observability hardening** (structured
> logging, `/metrics`, optional Sentry, hardened Docker images, CI, and
> backups — see `docs/DEPLOYMENT.md`), a **rule-based AI
> dispatch/prioritization engine** (see "AI dispatch engine" below), and a
> **visual drag-and-drop dispatch board with a live Leaflet/OpenStreetMap
> map and two-way SMS** (see "Live dispatch board, map & SMS" below) are all
> real and runnable. Models, migrations, services, routes, and tests for the
> **critical fixes**, for **auth + tenant onboarding**, for
> **customers/vessels/jobs**, for **invoices/payments/refunds/dunning/AR
> aging**, for **the customer portal + messaging**, and for **dispatch
> scoring** all exist and pass. Destination charges / application-fee
> revenue on top of Stripe Connect, a full customer password/login system
> (the portal uses durable magic links instead — see below), and a trained
> ML dispatch model are intentionally out of scope — see
> `../HarborIQ_v2_Corrected_Build_Spec.md` for the roadmap and "What's
> intentionally NOT here yet" below for the full deferred list.

## Stack

- **FastAPI** + **SQLAlchemy 2.0** (sync) + **Pydantic v2**
- **PostgreSQL 16** with **Row-Level Security** for tenant isolation
- **Alembic** migrations (SQL-file based)
- **pytest** (Postgres-backed integration tests)
- **Docker Compose** for local Postgres + app
- **GitHub Actions** CI (lint + migrate + test against a real Postgres service)

## What's fixed (vs. the original plan)

| Problem | Fix |
|---|---|
| Money/quantities as strings | `Numeric(12,2)` / `Integer` + `CHECK` + generated `line_total` |
| No DB-level tenant isolation | PostgreSQL RLS keyed on `app.current_company_id` + `FORCE ROW LEVEL SECURITY` |
| No tenant context for async/webhooks | `TenantContext` + webhook resolves company from Stripe metadata |
| Stripe webhook double-processing | `stripe_processed_events` + `ON CONFLICT DO NOTHING` idempotency |
| Public tokens underspecified | 256-bit entropy, hash-only storage, expiry, scope, revocation, audit |
| Inventory race condition | atomic conditional `UPDATE ... WHERE qty_on_hand >= :qty` |
| Implicit status strings | explicit state machines; transitions validated under row lock |
| Non-DB side effects in-tx | outbox table dispatched after commit |
| Tenant identity from a trusted header | Argon2id passwords + signed JWT access tokens; tenant read from the verified token |
| FK checks bypass RLS, so a tenant could reference a row it cannot see | composite `(company_id, id)` foreign keys make a cross-tenant reference unrepresentable |

## Two database roles

- `harboriq_app` — non-owner; **RLS applies**. Used by the API and tests.
- `harboriq_service` — **BYPASSRLS**; used only for webhook tenant resolution,
  public-token global lookup, and maintenance. Never serves tenant requests.

## Quick start

```bash
cp .env.example .env
docker compose up -d db          # Postgres + role creation
alembic upgrade head             # apply schema + RLS policies
pip install -e ".[dev]"
pytest -ra                       # Postgres-backed integration tests
uvicorn app.main:app --reload    # http://localhost:8000/docs
```

## Run the migration

```bash
DATABASE_URL=$SERVICE_DATABASE_URL alembic upgrade head
```
Migrations run as the **service** role (BYPASSRLS) so they can create RLS
policies and grant privileges.

## Tests

The critical-fix tests require a live Postgres with the schema migrated. They
connect as the **app role** so RLS is actually exercised.

```
tests/test_money_math.py                 # exact decimal math
tests/test_state_machines.py             # illegal transitions rejected
tests/test_rls_isolation.py             # cross-tenant read/write blocked
tests/test_inventory_concurrency.py     # one winner for the last unit
tests/test_public_tokens.py             # expiry, scope, revocation, atomicity
tests/test_stripe_webhook_idempotency.py # duplicate event applied once
tests/test_auth_signup_login.py         # signup, login, /me, token validation
tests/test_auth_refresh.py              # rotation, reuse detection, logout
tests/test_auth_rls.py                  # users/sessions isolated; header spoofing ignored
tests/test_auth_rbac.py                 # only owner/admin may provision users
tests/test_password_reset.py            # request, confirm, single-use, revocation
tests/test_crm_customers.py             # customer CRUD, search, name rule, role gate
tests/test_crm_vessels.py               # vessel CRUD, hull-id uniqueness, ownership
tests/test_crm_jobs.py                  # work-order CRUD, filters, customer/vessel pairing
tests/test_crm_job_status.py            # JobSM transitions, timestamps, who may move a job
tests/test_crm_job_dispatch.py          # assignment rules + the scheduling board feed
tests/test_crm_job_line_items.py        # labor/parts lines, invoiced freeze, inventory link
tests/test_crm_rls.py                   # cross-tenant isolation + tenant-safe foreign keys
tests/test_invoicing_create.py          # subtotal/tax/total math, line freezing, re-invoicing rules
tests/test_invoicing_lifecycle.py       # draft -> sent -> paid, draft/sent -> void, illegal transitions
tests/test_invoicing_rls.py             # cross-tenant isolation + composite FKs on invoices/payments
tests/test_public_invoice_pay.py        # token resolves invoice; read never burns a use; checkout URL
tests/test_stripe_invoice_webhook.py    # checkout.session.completed pays/partials an invoice, idempotently
tests/test_crypto_payments.py           # stablecoin checkout intent, HMAC webhook, idempotency, RLS isolation
tests/test_auth_rate_limit_lockout.py   # per-IP 429s, 5-failure lockout -> 423, expiry, generic messaging
tests/test_email_and_outbox_dispatch.py # console-fallback + real SMTP transport, dispatch_pending rewrite
tests/test_auth_invites.py              # invite create/preview/accept, role-escalation guard, tenant isolation
tests/test_dispatch_scoring.py          # pure scoring-function unit tests: urgency, revenue, distance, skill fit, workload
tests/test_dispatch_candidates.py       # ranked candidates endpoint, RBAC, tenant isolation, recompute persistence
tests/test_dispatch_queue.py            # ?sort=priority_score ordering, unscored jobs sort last, invalid sort -> 422
tests/test_stripe_connect.py            # Connect onboarding link, status, webhook account.updated, direct-charge fallback
tests/test_refunds.py                   # full/partial refunds, InvoiceSM transitions, over-refund rejected
tests/test_invoice_pdf_email.py         # PDF bytes generated, outbox invoice.send consumed into an actual email
tests/test_dunning.py                   # overdue selection, last_reminder_sent_at cadence, idempotent re-runs
tests/test_ar_aging.py                  # bucket math (1-30/31-60/61-90/90+), per-customer + grand totals
tests/test_portal_access.py             # portal token issue/resolve, non-consumption, expiry/revocation, tenant + customer isolation
tests/test_portal_data.py               # /me, /jobs, /invoices, /estimates scoping; estimate-approve reuses public flow
tests/test_portal_messages.py           # customer/staff send + list, outbox notifications, job-threaded messages, isolation
tests/test_portal_invite.py             # invite issues/renews a token + queues an email, role gating, cross-tenant 404
tests/test_user_profile.py              # self-edit vs admin-edit, restricted-field enforcement, tenant isolation, roster RBAC
tests/test_geocoding.py                 # mocked Nominatim: happy path, failure/timeout degrades gracefully, rate limiting, dispatch-distance integration
tests/test_geocode_backfill.py          # backfill only touches null-coordinate rows, tenant isolation, idempotency, admin-only route
tests/test_location_ping.py             # POST /users/me/location-ping validation, own-location-only, technician-locations RBAC + tenant isolation
tests/test_sms_service.py               # console-fallback vs real Twilio REST send, is_configured(), httpx failure never raises
tests/test_dispatch_board_assignment.py # board drag-and-drop reuses POST /jobs/{id}/assign; assignment queues a job-confirmation SMS
tests/test_sms_inbound_webhook.py       # inbound SMS -> messages(channel='sms'), staff-reply channel routing, unmatched-number drop, signature verification
tests/test_slips.py                     # slip CRUD, per-tenant identifier uniqueness, type/status CHECK constraints
tests/test_slip_reservations.py         # reservation lifecycle (SlipReservationSM), availability search, RBAC + tenant isolation
tests/test_slip_reservation_overlap.py  # genuinely concurrent double-booking attempt -> exactly one winner (btree_gist EXCLUDE)
tests/test_slip_storage_billing.py      # generate-storage-charge / generate-invoice reuse of the job_line_items -> invoices pipeline
```

## API surface

Every response (success or error, any endpoint below) carries an
`X-Request-ID` response header — either echoed back from the same header on
the inbound request (for when a reverse proxy already assigns one) or
freshly generated. Every log line emitted while handling that request
carries the same id, so a specific response can be correlated straight to
its server-side logs (see `app/api/middleware.py`, and
`docs/DEPLOYMENT.md` → "Logging").

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/healthz` | none | liveness |
| GET | `/api/v1/readyz` | none | readiness (DB check) |
| GET | `/metrics` | none† | Prometheus text-format request count + latency |
| POST | `/api/v1/auth/signup` | none | create a company (tenant) + its first owner, and log in |
| POST | `/api/v1/auth/login` | none, rate-limited + lockout | exchange email/password for an access + refresh token pair |
| POST | `/api/v1/auth/refresh` | refresh token | rotate the pair; the presented token is invalidated |
| POST | `/api/v1/auth/logout` | bearer | revoke this device's session (or every device's) |
| GET | `/api/v1/auth/me` | bearer | the authenticated user |
| POST | `/api/v1/auth/users` | bearer, owner/admin | provision a user inside the caller's company (admin sets the password) |
| POST | `/api/v1/auth/password-reset/request` | none, rate-limited | queue a reset email (always 202) |
| POST | `/api/v1/auth/password-reset/confirm` | reset token | set a new password and revoke every session |
| POST | `/api/v1/auth/invites` | bearer, owner/admin | issue a one-time invite link for a new teammate (invitee sets their own password) |
| GET | `/api/v1/auth/invites/{token}` | none | read-only preview (email/role/company) for the accept-invite page; does not consume |
| POST | `/api/v1/auth/invites/{token}/accept` | none | consume the invite, create the account, and log the new user straight in |
| POST | `/api/v1/customers` | bearer, owner/admin/office | create a customer |
| GET | `/api/v1/customers` | bearer | list/search customers (name, email, phone) |
| GET | `/api/v1/customers/{id}` | bearer | one customer |
| GET | `/api/v1/customers/{id}/vessels` | bearer | that customer's fleet |
| PATCH | `/api/v1/customers/{id}` | bearer, owner/admin/office | partial update |
| DELETE | `/api/v1/customers/{id}` | bearer, owner/admin/office | delete; 409 while vessels or jobs reference it |
| POST | `/api/v1/vessels` | bearer, owner/admin/office | register a boat against a customer |
| GET | `/api/v1/vessels` | bearer | list the fleet; filter by `customer_id`, search the spec sheet |
| GET | `/api/v1/vessels/{id}` | bearer | one vessel |
| PATCH | `/api/v1/vessels/{id}` | bearer, owner/admin/office | partial update, including reassignment |
| DELETE | `/api/v1/vessels/{id}` | bearer, owner/admin/office | delete; 409 while jobs reference it |
| POST | `/api/v1/jobs` | bearer, owner/admin/office | open a work order |
| GET | `/api/v1/jobs` | bearer | the queue; filter by status, priority, technician, customer, vessel, date, `unassigned` |
| GET | `/api/v1/jobs/schedule` | bearer | calendar/board feed for `[start, end)`, optionally per technician |
| GET | `/api/v1/jobs/{id}` | bearer | one work order with its line items |
| PATCH | `/api/v1/jobs/{id}` | bearer, owner/admin/office | edit descriptive + scheduling fields (never status) |
| DELETE | `/api/v1/jobs/{id}` | bearer, owner/admin/office | delete the job and its lines |
| POST | `/api/v1/jobs/{id}/assign` | bearer, owner/admin/office | dispatch to a technician (null unassigns) |
| GET | `/api/v1/jobs?sort=priority_score` | bearer | the queue ordered by cached `dispatch_score` (unscored jobs sort last) |
| GET | `/api/v1/jobs/{id}/dispatch/candidates` | bearer, owner/admin/office | rank active technicians for this job by explainable dispatch score |
| POST | `/api/v1/jobs/{id}/dispatch/recompute` | bearer, owner/admin/office | recompute + cache the job's technician-independent priority score |
| POST | `/api/v1/jobs/{id}/status` | bearer, office or the assigned tech | move through `JobSM`; 409 on an illegal transition |
| POST | `/api/v1/jobs/{id}/line-items` | bearer, office or the assigned tech | record labor, a part or a fee |
| GET | `/api/v1/jobs/{id}/line-items` | bearer | the job's billable lines |
| PATCH | `/api/v1/jobs/{id}/line-items/{line_id}` | bearer, office or the assigned tech | correct a line; 409 once invoiced |
| DELETE | `/api/v1/jobs/{id}/line-items/{line_id}` | bearer, office or the assigned tech | remove a line; 409 once invoiced |
| POST | `/api/v1/inventory/use` | bearer | atomic stock deduction; with `job_id`, bills the part to that work order |
| POST | `/api/v1/inventory` | bearer, owner/admin/office | register a new inventory item (starts at `quantity_on_hand = 0`) |
| GET | `/api/v1/inventory` | bearer | list/search inventory; `low_stock_only=true` filters to items at/below their reorder point |
| GET | `/api/v1/inventory/lookup?sku=...` | bearer | resolve a SKU straight to its item (barcode-scan-or-type workflow) |
| GET | `/api/v1/inventory/reorder-suggestions` | bearer | items at/below their reorder point, annotated with `default_vendor_id` |
| POST | `/api/v1/inventory/reorder-suggestions/generate-po` | bearer, owner/admin/office | create one `draft` PO from selected low-stock items and a vendor; nothing submitted to the vendor yet |
| GET | `/api/v1/inventory/{id}` | bearer | one inventory item |
| PATCH | `/api/v1/inventory/{id}` | bearer, owner/admin/office | partial update |
| POST | `/api/v1/vendors` | bearer, owner/admin/office | create a vendor |
| GET | `/api/v1/vendors` | bearer | list/search vendors by name |
| GET | `/api/v1/vendors/{id}` | bearer | one vendor |
| PATCH | `/api/v1/vendors/{id}` | bearer, owner/admin/office | partial update; no delete endpoint (see "Inventory, parts & vendors") |
| POST | `/api/v1/vendors/{id}/status` | bearer, owner/admin/office | deactivate (archive) or reactivate a vendor (Phase 17) |
| POST | `/api/v1/purchase-orders` | bearer, owner/admin/office | create a `draft` PO with its line items |
| GET | `/api/v1/purchase-orders` | bearer | list POs; filter by `status` |
| GET | `/api/v1/purchase-orders/{id}` | bearer | one PO with its line items |
| POST | `/api/v1/purchase-orders/{id}/submit` | bearer, owner/admin/office | `draft` -> `submitted`: the human commitment point |
| POST | `/api/v1/purchase-orders/{id}/receive` | bearer, owner/admin/office | record received quantities (may be partial); increments `quantity_on_hand` through the same guarded writer `POST /inventory/use` decrements it with |
| POST | `/api/v1/purchase-orders/{id}/cancel` | bearer, owner/admin/office | `draft`/`submitted` -> `cancelled`; not allowed once `received` |
| POST | `/api/v1/invoices` | bearer, owner/admin/office | invoice every currently-uninvoiced line on a job |
| GET | `/api/v1/invoices` | bearer, owner/admin/office | list invoices; filter by status, customer, job |
| GET | `/api/v1/invoices/{id}` | bearer, owner/admin/office | one invoice with its frozen line items |
| POST | `/api/v1/invoices/{id}/send` | bearer, owner/admin/office | draft -> sent; mints a Stripe Checkout Session (best-effort) and a public pay token |
| POST | `/api/v1/invoices/{id}/void` | bearer, owner/admin/office | draft/sent -> void; 409 if any payment has already landed; frees line items for re-invoicing |
| POST | `/api/v1/invoices/{id}/refund` | bearer, owner/admin/office | full/partial refund against `amount_paid`; lands on `refunded`/`partially_refunded` via `InvoiceSM` |
| POST | `/api/v1/invoices/{id}/crypto-payment-intent` | bearer, owner/admin/office | create a licensed-processor stablecoin checkout for a sent/partial invoice (Phase 18 feature flag) |
| GET | `/api/v1/crypto-payments/{id}` | bearer, owner/admin/office | one tenant-scoped stablecoin payment request/outcome |
| POST | `/api/v1/billing/connect/onboarding-link` | bearer, owner/admin | create (or resume) this company's Stripe Connect account + a fresh onboarding link |
| GET | `/api/v1/billing/connect/status` | bearer, owner/admin | this company's Connect account id + `charges_enabled`/`details_submitted` |
| POST | `/api/v1/billing/dunning/run` | bearer, owner/admin | run the overdue-reminder sweep on demand; returns reminded invoice ids |
| GET | `/api/v1/reports/ar-aging` | bearer, owner/admin/office | outstanding balances bucketed 1-30/31-60/61-90/90+ days past due, per customer + totals |
| GET | `/api/v1/public/invoice/{token}` | public token | read-only pay page: invoice, line items, live checkout URL |
| POST | `/api/v1/public/estimate/{token}/approve` | public token | public estimate approval (e-sign) |
| POST | `/api/v1/webhooks/stripe` | Stripe signature | idempotent Stripe webhook (subscription billing *and* invoice payment) |
| POST | `/api/v1/webhooks/crypto` | HMAC-SHA256 signature | idempotent licensed-processor stablecoin payment webhook (Phase 18) |
| POST | `/api/v1/customers/{id}/portal-invite` | bearer, owner/admin/office | issue (or renew) a customer's durable portal magic link and email it |
| GET | `/api/v1/portal/{token}/me` | portal token | that customer's profile + vessels only |
| GET | `/api/v1/portal/{token}/jobs` | portal token | that customer's job history (status/schedule/technician, no internal notes or pricing) |
| GET | `/api/v1/portal/{token}/invoices` | portal token | that customer's invoices |
| GET | `/api/v1/portal/{token}/invoices/{invoice_id}/pay-url` | portal token | a fresh checkout URL for one of that customer's invoices (reuses `get_or_create_checkout_url`) |
| GET | `/api/v1/portal/{token}/estimates` | portal token | that customer's estimates |
| POST | `/api/v1/portal/{token}/estimates/{estimate_id}/approve-token` | portal token | mints a short-lived `estimate_approve` token for the SAME existing public approval endpoint |
| GET, POST | `/api/v1/portal/{token}/messages` | portal token | that customer's message thread; POST sends a new customer message |
| GET | `/api/v1/portal/{token}/dock-locations` | portal token | that customer's own confirmed/checked-in slip reservation(s) with GPS coordinates, for the "find my dock" map (Phase 17) |
| GET | `/api/v1/messages` | bearer, owner/admin/office | company-wide staff inbox, newest first; `unread_only=true` narrows to unread customer messages |
| POST | `/api/v1/messages` | bearer, owner/admin/office | staff reply/send to a customer's thread |
| POST | `/api/v1/messages/{id}/read` | bearer, owner/admin/office | mark a message read |
| GET | `/api/v1/messages/by-job/{job_id}` | bearer, owner/admin/office | every message tied to one job, oldest first |
| GET | `/api/v1/users` | bearer, owner/admin/office | team roster: every user in the caller's company, incl. skills, address, geocoded home coordinates |
| PATCH | `/api/v1/users/{id}` | bearer (self) or owner/admin (anyone in-company) | edit `full_name`/`skills`/`address_text` (self or admin); `role`/`is_active` restricted to owner/admin editing someone else |
| POST | `/api/v1/admin/geocode-backfill` | bearer, owner/admin | geocode every customer/user in the caller's company that has an address but no coordinates yet; `?force=true` re-geocodes everything |
| POST | `/api/v1/users/me/location-ping` | bearer | record the caller's own current `{latitude, longitude}` for the dispatch board map (best-effort, tab-open only) |
| GET | `/api/v1/users/technician-locations` | bearer, owner/admin/office | every technician's best-known position (live ping or static geocoded home fallback) for the map |
| POST | `/api/v1/jobs/{id}/notify-on-my-way` | bearer, office or the assigned tech | send an "on my way" SMS to the job's customer (best-effort; silent no-op if no phone on file) |
| POST | `/api/v1/webhooks/sms/inbound` | Twilio signature (once configured) | inbound SMS/MMS webhook; matches the sender's phone to a customer and appends to the existing Phase 9 messages thread |

† `/metrics` is unauthenticated on purpose (standard practice for Prometheus
scraping), but should be firewalled to the scraper's network at the reverse
proxy in any real deployment — see `docs/DEPLOYMENT.md` → "Metrics".

## Auth

**Scheme: stateless HS256 JWT access tokens (15 min) + opaque, rotating,
server-stored refresh tokens (30 days).**

Why this and not server-side sessions: the app is sync SQLAlchemy behind
FastAPI and every request already opens a DB session, but a session-cookie
scheme would also need CSRF protection and a cookie/CORS story for the React
client that comes in a later phase. A bearer access token keeps the request
path to one indexed lookup, works unchanged for the future SPA and for
machine clients, and keeps the revocation story honest by putting the
long-lived credential (the refresh token) in the database where it can
actually be revoked.

How a request is authorised, end to end:

1. `POST /auth/login` resolves the email through the **service role**
   (BYPASSRLS) — the only way to find a user before a tenant is known — then
   verifies the Argon2id hash and issues the pair under the **app role**.
2. The access token carries `sub` (user), `cid` (company), `role` and `sid`
   (session). It is signed with `JWT_SECRET` and checked for `iss`/`exp`.
3. `app/api/deps.py::get_current_principal` verifies the signature, re-reads
   the user row, and calls `set_tenant()` to arm `app.current_company_id`.
   **Every route therefore runs under exactly the same RLS mechanism as
   before — the tenant is just derived from a verified token instead of a
   trusted header.**
4. Authorization reads `role` from the database row, not the JWT claim, so a
   demotion or deactivation takes effect immediately rather than at token
   expiry. `require_roles(...)` enforces it; `POST /auth/users` is restricted
   to owner/admin, and only an owner can create another owner.

Token and credential handling:

- Passwords are hashed with **Argon2id** (`argon2-cffi`), re-hashed on login
  when the parameters change. Minimum length is `PASSWORD_MIN_LENGTH`.
- Refresh tokens are 256-bit random values stored **only as SHA-256 hashes**,
  the same discipline as public tokens.
- Rotation is a single conditional `UPDATE ... WHERE rotated_at IS NULL`, so
  concurrent refreshes yield exactly one winner. Presenting an
  already-rotated token is treated as theft: the whole token **family** is
  revoked and the event is audited.
- Password reset delivers its token through the **outbox**, never in the HTTP
  response, and confirming a reset revokes every session for that user.
- Login and password-reset responses are identical for known and unknown
  emails, so neither can be used to enumerate accounts.

One email addresses exactly one account platform-wide (enforced by a unique
index, which RLS does not weaken) — login has no tenant context to
disambiguate with. Multi-company membership would need a join table and a
tenant-selection step; that is deliberately deferred.

Required configuration — see `.env.example`. `JWT_SECRET` ships as an obvious
placeholder and is **rejected at startup** unless `APP_ENV=development`.

## Auth hardening (rate limiting, lockout, invites)

Three production-hardening pieces were added on top of the auth layer above,
scoped to what a pilot needs before its first real customer, not a fully
general security platform:

**Rate limiting.** `app/core/rate_limit.py` implements a small in-process
fixed-window counter (`_FixedWindowLimiter`), keyed by client IP, with
independent windows per endpoint family (`login` and `password-reset` do not
share a budget). Default is `rate_limit_requests_per_window=10` requests per
`rate_limit_window_seconds=60`; exceeding it returns `429` with a `Retry-After`
header. This is deliberately **not** Redis-backed — a single-process in-memory
dict is the honest scope for one API instance behind a pilot's load, and the
module's docstring flags upgrading to a shared store (Redis `INCR`+`EXPIRE`,
or a token-bucket at the edge/CDN) as the change needed the moment there is
more than one backend process, since separate processes would each keep their
own counters and the effective limit would multiply per instance.

**Account lockout.** `users.failed_login_attempts` and `users.locked_until`
(added in migration `0005`) track failures per account, independent of the
per-IP rate limiter above — this stops a distributed attacker credential-
stuffing one account from many IPs, which the rate limiter alone would not
catch. After `login_max_failed_attempts` (default 5) consecutive failures the
account locks for `login_lockout_minutes` (default 15) and every attempt
during that window — even with the correct password — returns `423 Locked`
with a message that never echoes the email address or a countdown, matching
the existing enumeration-avoidance stance of login/password-reset. A
successful login resets the counter to zero. This is checked and incremented
under a `SELECT ... FOR UPDATE` on the user row inside the same transaction as
the password verification, so concurrent login attempts against the same
account cannot race past the threshold.

**Email transport.** `app/services/email.py::send_email` sends real SMTP
(`smtplib.SMTP`/`SMTP_SSL`, STARTTLS via `smtp_use_tls`) when `smtp_host` is
configured, and otherwise falls back to logging the full message at INFO —
the same "console transport" pattern most frameworks ship for local dev, so a
contributor never needs a real mailbox to exercise password-reset or invite
flows. `app/services/outbox.py::dispatch_pending` was rewritten to actually
call it (previously a skeleton that left rows queued forever): it claims rows
with `FOR UPDATE SKIP LOCKED` (so concurrent dispatchers never double-send),
builds the right email for each `event_type` (`auth.password_reset_requested`,
`user_invite.sent`, `invoice.send`, `receipt.send`), and ages a row to
`dead_letter` after `MAX_DISPATCH_ATTEMPTS` (5) consecutive failures rather
than retrying forever. Dispatch is triggered via FastAPI `BackgroundTasks`
scheduled in the route handler right after the triggering transaction
commits (`app/services/outbox_dispatch.py::dispatch_outbox_soon`) — **not**
Celery/Redis. That trade-off is deliberate for this phase: it needs zero new
infrastructure and the delivery window is a couple of seconds after the
request, which is fine for password resets and invites; the real limitation is
that a `BackgroundTasks` job dies with the worker process, so anything queued
at the moment of a crash/restart is only picked up on the *next* successful
dispatch trigger, not retried on a schedule. A Celery/Redis (or APScheduler)
periodic sweep of `outbox_events` is the natural upgrade once there is
operational reason to guarantee delivery independent of new requests arriving.

**Invite-link user provisioning.** `POST /auth/invites` (owner/admin only,
same role-escalation rule as `POST /auth/users` — an admin cannot invite an
owner) issues a single-use, 168-hour token reusing the existing
`public_tokens` table with a new `user_invite` enum value on `token_purpose`
(migration `0005`, `ALTER TYPE ... ADD VALUE`) rather than a bespoke invites
table — the invite is structurally identical to every other token this
codebase already issues (hashed at rest, `expires_at`, `max_uses`,
`revoked_at`), so reusing the table means invite tokens get the same proven
expiry/revocation/use-limit enforcement for free instead of a second
implementation to keep in sync. `GET /auth/invites/{token}` is a read-only
preview for the accept-invite page (email/role/company name) that never
consumes a use, so a candidate can reload the page. `POST
/auth/invites/{token}/accept` consumes the token, creates the user with a
password the invitee chooses themselves (routed through the same
`hash_password`/`validate_password_strength` path as signup — no divergent
validation logic), and logs them straight in. All three 404 identically for
an unknown, expired, revoked, or already-used token, the same
enumeration-avoidance stance as the password-reset and invoice pay-link
endpoints.

One implementation detail worth documenting because it was a real bug caught
by testing, not a hypothetical: `accept_invite` locks and consumes the
`public_tokens` row (`SELECT ... FOR UPDATE` + the consuming `UPDATE`) on the
**same** DB session/transaction as the user `INSERT`, inside one
`tenant_context`. An earlier draft resolved+locked the token on the
service-role session (needed first, to discover which tenant the token
belongs to before a tenant context can even be opened) and then tried to
consume it on the app-role session used for the tenant-scoped writes — two
different sessions/connections. That split a row lock from the mutation it
was protecting: the second session's `UPDATE` blocked forever waiting on the
first session's still-open, uncommitted lock, which was never released until
the request ended — a guaranteed hang on every accept-invite call under any
concurrent load, caught by a hanging test run rather than by inspection. The
fix — and the general rule now followed anywhere this pattern recurs — is
that a row lock and the write it guards must never be split across two DB
sessions; the service-role session here is used only for a non-locking
precheck (with an explicit `commit()` immediately after, so it never idles in
a transaction) to learn the tenant, and the actual lock+consume+insert all
happen together on the app-role session.

**Explicitly out of scope for this phase** (see "What's intentionally NOT
here yet" below for the full, consolidated list): stateful access-token
revocation was still absent at this point (a revoked session's *access*
token — as opposed to its refresh token, which *is* revoked immediately —
still worked until it expired). It shipped in [Phase 17 — Backlog
Completion](#phase-17--backlog-completion). MFA/TOTP enrollment shipped in
Phase 16 — see below.

## Enterprise hardening: Redis/Celery, httpOnly cookies, MFA, backups, CDN (Phase 16)

Six pieces of production hardening, each closing a gap this README had
previously and explicitly called "deferred" in an earlier phase:

**1. Redis-backed rate limiting + Celery.** The in-process, per-instance
rate limiter described under "Auth hardening" above is now backed by Redis
(`app/core/rate_limit.py`) — a Lua script run via `EVAL` does the
increment-and-check atomically server-side, so the limit is enforced
globally across every `app` replica instead of once per replica. It **fails
open**: if Redis is unreachable, requests are allowed rather than the whole
app going down over a rate-limiter dependency. The `BackgroundTasks` outbox
dispatch and the Phase 8 dunning sweep / Phase 10 geocode backfill scripts
now run as real Celery tasks (`app/tasks/outbox_tasks.py`,
`app/tasks/sweep_tasks.py`) against the same Redis instance as broker +
result backend, with Celery Beat driving the periodic sweeps that
previously needed an external cron caller. Every task is a thin wrapper
around the same underlying claim-and-process function the old code path
used (`app.services.outbox.dispatch_pending`, `app.jobs.dunning_sweep.run`,
`app.jobs.geocode_backfill.run`) — the `FOR UPDATE SKIP LOCKED` claiming
semantics live in exactly one place, so a Celery worker can never race a
direct call to the same function with divergent logic. In tests, Celery
runs in eager mode (see `tests/conftest.py`'s `_celery_eager_mode` autouse
fixture) so a task executes synchronously in-process rather than needing a
real worker/broker in CI.

**2. httpOnly-cookie refresh tokens + CSRF.** The refresh token, previously
returned in the JSON body and stored in the frontend's `localStorage` (an
explicit Phase 5 MVP trade-off — see "Frontend" below), now travels only as
an **httpOnly, SameSite=Lax** cookie set directly by the backend
(`app/api/v1/routes/auth.py`) — frontend JavaScript can no longer read it
at all, which closes the XSS-can-steal-the-refresh-token risk `tokenStore.ts`
had flagged. Because a cookie is attached to requests automatically
regardless of which page triggered them, `app/core/csrf.py` adds a
standard double-submit-cookie check on top of `SameSite=Lax`: a second,
NON-httpOnly `csrf_token` cookie is set alongside the refresh cookie, the
frontend echoes its value back in an `X-CSRF-Token` header on every
cookie-reliant request, and the backend rejects the request if the two
don't match — a cross-site attacker can make the browser *send* the
httpOnly cookie, but same-origin policy stops it from *reading*
`document.cookie` to forge the matching header. `src/lib/tokenStore.ts` no
longer stores a refresh token at all; `AuthContext.tsx`'s session-hydration
effect now gates on the presence of the readable CSRF cookie instead (its
presence is the only frontend-visible signal that a session might exist).

**3. MFA / TOTP.** Migration `0014` adds `users.mfa_enabled_at` and a new
`mfa_backup_codes` table (RLS-enabled and forced, same tenant-isolation
convention as every other table). `app/services/mfa.py` implements
enroll → confirm → disable, backed by `pyotp` for TOTP generation/
verification and the existing `app/core/crypto.py` Fernet helpers to
encrypt the secret at rest in `users.mfa_secret_enc` (never stored
plaintext). Confirming a pending enrollment issues **10 single-use backup
codes** (format `XXXX-XXXX`, hashed at rest with the same Argon2id hasher
already used for passwords) for the case a user loses their authenticator
device. Login gains a genuine second factor: `POST /auth/login` returns
`{"mfa_required": true, "pre_auth_token": "..."}` instead of real tokens
when the account has MFA active — no session is created yet, nothing to
revoke if the flow is abandoned here — and `POST /auth/login/mfa` exchanges
that 5-minute-TTL pre-auth token plus a TOTP or backup code for the real
token pair. The pre-auth token is a JWT with a distinct `typ` claim
(`mfa_pre_auth`, not `access`), so a real access token can never be replayed
as a pre-auth token and vice versa — enforced by the JWT decoder rejecting
a mismatched `typ`, not by convention. Frontend: **Security** in the app
nav (`/settings/security`) renders the QR code (`qrcode.react`) during
enrollment and lets a user view remaining backup-code count / disable MFA
(disable requires re-entering the current password); `LoginPage.tsx` grows
a second screen for the code prompt when `login()` resolves to a
`{ preAuthToken }` challenge instead of logging in directly. MFA was
initially always self-service and optional; [Phase 17 — Backlog
Completion](#phase-17--backlog-completion) adds the company-wide,
admin-forced policy described there.

**4. Off-host S3 backups.** `scripts/backup_db_s3.sh` wraps the existing
`scripts/backup_db.sh` (unchanged) and adds an `aws s3 cp` push of the
resulting dump when `BACKUP_S3_BUCKET` is set, and **degrades gracefully to
an identical local-only backup, exiting 0, when it is not** — the same
graceful-degrade convention this codebase already used for
`smtp_host`/`stripe_api_key`/`twilio_account_sid`. See
`docs/DEPLOYMENT.md`'s "Off-host backups to S3" section for the exact env
vars and IAM/bucket setup an operator needs to do to activate it — none of
which this repo can provision itself (no AWS account exists in this
sandbox to test against; the script's behavior with S3 configured was
verified only via the graceful-degradation and missing-CLI code paths, not
an actual S3 upload).

**5. Cloudflare CDN/WAF — documentation only.** No CDN/WAF was actually
provisioned (same reasoning as #4 — no Cloudflare account exists in this
sandbox). `docs/DEPLOYMENT.md`'s new "CDN / WAF (Cloudflare)" section
documents the DNS/proxy-mode, cache-rule (static assets only, **never**
`/api/*`), and WAF-rule configuration an operator would apply on top of
the reverse proxy already documented, including the one rule that matters
most for correctness rather than performance: API responses must never be
edge-cached, because they are per-tenant and often mutate state as a side
effect of being called.

**6. Multi-instance readiness audit.** With Redis-backed rate limiting and
Celery now in place, `app` is close to safe to run as N replicas — this
phase audited the codebase for any remaining per-instance state and found
exactly one: `app/services/geocoding.py`'s outbound-request throttle to
the (rate-limited) third-party geocoding provider, which is deliberately
left in-process (it throttles *outbound* calls to a third party, not a
security/tenant-isolation control — see `docs/DEPLOYMENT.md`'s "Running
more than one app instance" section for the full reasoning and what would
change to move it to Redis too, if ever needed).

## CRM and operations

Three tables carry the day-to-day work: a **customer** owns **vessels**, and a
**job** (work order) is opened against one customer and optionally one of that
customer's boats. All three are RLS-isolated with the same
`FORCE ROW LEVEL SECURITY` + `app.current_company_id` pattern as the rest of the
schema, and every service call runs on the app role inside `tenant_context`, so
isolation never depends on a developer remembering a `WHERE company_id = ...`.

**Cross-tenant references are unrepresentable, not merely unlikely.** A plain
`REFERENCES customers(id)` is validated by an internal system query that RLS
does *not* apply to, so tenant A could point a vessel at a customer it cannot
even read. Migration 0003 adds `UNIQUE (company_id, id)` to every referenced
table and rewrites the foreign keys as composite `(company_id, <id>)` keys.
`tests/test_crm_rls.py` is the proof.

**Status moves only through the existing state machine.**
`app/services/state_machines.py::JobSM` already described the legal job
transitions; this phase reuses it rather than inventing a second source of
truth. `POST /jobs/{id}/status` calls `jobs.set_status`, which:

1. re-reads the row with `SELECT status ... FOR UPDATE`, so the machine is
   consulted against the *actual* current status rather than one the client
   sent;
2. calls `JobSM.assert_transition(current, target)` — a rejection is a 409 and
   nothing is written;
3. applies the transition together with its bookkeeping in one statement:
   `in_progress` stamps `started_at` (via `COALESCE`, so resuming from a hold
   keeps the original start) and clears `hold_reason`, `on_hold` records the
   reason, and `completed`/`canceled` stamp their timestamps.

Taking the row lock *before* asserting is what makes it safe under concurrency:
two racing requests to start the same job serialise, and the loser re-reads
`in_progress` and is rejected instead of double-applying. `PATCH /jobs/{id}`
deliberately has no `status` field.

**Line items are the invoicing phase's input, and are built for it now.**
`job_line_items` records labor, parts and fees with `quantity`/`unit_price` as
`NUMERIC(12,2)` (fractional, because labor is billed in hours) and a
`line_total` that is a `GENERATED ALWAYS AS (quantity * unit_price) STORED`
column, so the app can never disagree with the database about a total. Each
line carries `taxable`, a nullable `invoice_id`/`invoiced_at` pair guarded by a
CHECK that they are set together, and an `inventory_committed` flag. Invoicing
itself is **not** built: nothing in this phase writes `invoice_id`, but once
something does, that line becomes immutable — edits and deletes answer 409.

**Inventory has exactly one writer.** Naming an `inventory_item_id` on a line
item only records which part was fitted; it does not move stock.
`POST /api/v1/inventory/use` remains the single writer of `quantity_on_hand`,
and when given a `job_id` it appends its own committed `part` line *in the same
transaction* as the deduction — so a part can never be off the shelf without
being on the work order, or vice versa.

**Roles.** Owner/admin/office run the shop: they own the customer book, the
fleet, and job creation, editing, dispatch and deletion. A technician can read
those records, and on a job assigned to *them* may move the status and record
the labor and parts they used. Probing another tenant's job id returns 404, not
403, so a 403 never confirms that a record exists. Dispatch is restricted to
active users holding a role in `JOB_ASSIGNABLE_ROLES` (technician, admin,
owner) — office staff take the call, they do not turn the wrenches.

## AI dispatch engine

**This is a rule-based, explainable priority scorer — not a trained model, and
that is a deliberate architecture choice, not a shortcut.** "AI dispatching"
at this stage of the platform's life honestly means transparent weighted
scoring, because there is no real repair-outcome data yet to train anything
meaningful on: a pre-revenue pilot with a handful of shops has no labeled
history of "this dispatch decision led to a good outcome" to learn from, and
faking a model against no data would be worse than admitting that and
shipping something honest. The heuristic carried over from the earlier design
discussion is to revisit this once the platform has accumulated **roughly
500+ real, labeled repair outcomes** (job completed, on time or not, redo or
not, customer satisfaction where captured) — enough rows that a model would
actually be learning a pattern instead of memorizing noise. Until then, every
score is a sum of named, capped factors that a shop owner can see and argue
with, which also makes it debuggable in a way an opaque model would not be.

**`app/services/dispatch.py::score_job` is a pure function: no DB access, so
it is fully unit-testable against plain fixtures.** It returns a `DispatchScore`
(a `total` plus a `breakdown` dict, one entry per factor) rather than a bare
number, because a dispatcher deciding *between* two similarly-scored
candidates needs to see *why* one edged out the other, not just that it did.
Weights (all module-level named constants, easy to retune without touching the
scoring logic itself):

| Factor | Weight | Behavior |
|---|---|---|
| Urgency | 50 | Priority base (low 0.10 / normal 0.35 / high 0.65 / urgent 0.90) blended toward 1.0 as the job goes overdue, saturating at 6 days overdue. Dominant by design — a $50 urgent job outranks a $5,000 low-priority one. |
| Technician skill fit | 15 | Jaccard overlap of the job's `required_skills` against the candidate's `skills`. Neutral (full weight) if the job has no required skills; a real zero if it has required skills the candidate shares none of. |
| Revenue | 15 | `log1p` curve on the job's line-item revenue, saturating around $5,000 — diminishing returns so a single huge invoice cannot dwarf urgency. |
| Distance | 12 | Haversine miles from technician to customer, exponential half-life falloff (half-life 15 miles). **Graceful degradation:** scores neutral (0.00) rather than penalizing when either side is missing coordinates, since most customers do not have geocoded addresses yet (see deferred list). |
| Customer value | 8 | The customer's completed-job count, saturating at 12 — a mild loyalty signal, not a hard gate. |
| Parts availability | 10 | **Real signal as of Phase 13** (previously a documented permanent no-op — the weight was reserved from Phase 7 specifically so this could be wired in later as a pure addition, not a rescoring of every other factor). `_compute_inventory_shortfall` sums the job's `part`-kind line items against current `quantity_on_hand`: full weight if the job has no tracked parts or every needed part is in stock, zero (not negative) if any linked part needs more than is on hand. See "Inventory, parts & vendors (Phase 13)" below for the full mechanism. |
| Workload | −6 (penalty) | Subtracted, not added: a technician's current active-job count, saturating at 5 concurrent jobs, so the engine spreads load instead of piling everything onto whoever scores best on the other factors. |

**Two scoring entry points, because "prioritize the queue" and "who should do
this job" are different questions.** `recompute_and_cache_score` computes and
persists the job-level score using only the technician-independent factors
(urgency, revenue, customer value, parts availability) onto
`jobs.dispatch_score`/`dispatch_score_breakdown`/`dispatch_scored_at`, powering
`GET /api/v1/jobs?sort=priority_score` for the intake queue/schedule board
regardless of who ends up assigned. `rank_technicians_for_job` computes a
full per-candidate score — the same job-level factors *plus* distance, skill
fit and workload for that specific technician — for
`GET /api/v1/jobs/{id}/dispatch/candidates`, restricted to active users in
`JOB_ASSIGNABLE_ROLES` (technician, admin, owner), the same set the assignment
endpoint itself allows. Both routes are gated to owner/admin/office
(`require_operations`) — a technician can see and work their own assigned job,
but ranking every technician in the shop is an operations decision.

**Schema (migration `0006_dispatch_engine`).** `users` gained `skills
TEXT[]` and `home_latitude`/`home_longitude NUMERIC(9,6)` (paired by a CHECK
constraint — either both set or both null); `companies` and `customers` each
gained `latitude`/`longitude NUMERIC(9,6)` with the same pairing CHECK; `jobs`
gained `required_skills TEXT[]` plus the cache columns `dispatch_score
NUMERIC(6,2)`, `dispatch_score_breakdown JSONB`, and `dispatch_scored_at
TIMESTAMPTZ`. There is deliberately no endpoint yet to set a technician's
`skills` or home coordinates — this repo has no user-management/update
endpoints at all yet (see deferred list), so today those columns are set
directly in the database; the scoring engine and its graceful degradation for
missing coordinates were built expecting that gap to close later, not around
it staying open forever.

## Invoicing & payments

**A job's uninvoiced line items are the only input.** `POST /api/v1/invoices`
locks every `job_line_items` row on the job with `invoiced_at IS NULL` under
`FOR UPDATE`, sums `subtotal` from real `Decimal` math (not float), applies
`tax_rate` only to lines with `taxable = true` to get `tax_total`, inserts the
invoice with `total = subtotal + tax_total` and `balance_due = total`, then
attaches every locked line to it (`invoice_id`, `invoiced_at`) in the same
transaction. A job with nothing left to invoice — never billed anything, or
already fully invoiced — is a 409, not an empty invoice. `job_line_items`
already went immutable once invoiced back in the CRM phase; invoicing is the
first thing that actually sets that flag.

**Status moves through `InvoiceSM`, the same pattern as `JobSM`.** `send_invoice`
and `void_invoice` both re-read the invoice with `SELECT ... FOR UPDATE` before
calling `InvoiceSM.assert_transition`, so two racing requests serialise instead
of double-sending or double-voiding. `InvoiceSM.transitions["draft"]` now
includes `"void"` in addition to `"sent"` — a draft that should never be billed
(bad job, duplicate, customer walked away) can be cancelled directly instead of
forcing a pointless send-then-void round trip that would also mint a live
Stripe Checkout Session for nothing. Voiding is rejected with 409 once
`amount_paid > 0`: money that has already moved cannot be waved away by a
status change, only by a refund (deferred, see below). Voiding a still-unpaid
invoice frees its line items (`invoice_id`/`invoiced_at` cleared) so they can
be corrected and re-invoiced.

**Sending an invoice is best-effort against Stripe, never blocking on it.**
`send_invoice` tries to create a Stripe Checkout Session for the invoice total,
but a Stripe outage or missing API key must not stop the shop from sending the
invoice — `stripe_billing.create_checkout_session` swallows any exception and
returns `None`, and the invoice still moves to `sent` either way. What it does
not skip is the public pay token: every sent invoice gets an `invoice_pay`
token (`app/services/public_tokens.py`, 720-hour TTL, 50 uses) so the customer
always has a durable link even if the first Stripe session attempt failed —
the pay page itself lazily creates a session on read if one is still missing.

**The public pay page is read-only by design.** `GET
/api/v1/public/invoice/{token}` resolves the token with the new
`resolve_read_only_token()` and deliberately does **not** call the
uses-incrementing path that `estimate_approve` tokens use — a customer opening
the emailed link five times while deciding whether to pay must not burn
through a 50-use budget or trip an expiry race against their own browser
reloads. The only state-changing operation for a customer invoice is the
Stripe webhook; this endpoint only ever reads and, when the invoice is still
payable, lazily persists a fresh Stripe Checkout Session URL (never caches the
URL itself, only the session id, so the link always reflects current Stripe
state).

**The Stripe webhook now disambiguates two unrelated event families.** Phase 2
already handled Stripe *Billing* subscription invoices
(`invoice.payment_succeeded`, HarborIQ's own SaaS subscription revenue) —
that handler is renamed `_on_subscription_payment_succeeded` (still the
original TODO stub; `tests/test_stripe_webhook_idempotency.py` passes against
it unmodified) to make room for the *new*, unrelated concept this phase adds:
a marine shop's own customer paying their invoice through a Checkout Session
carrying `metadata.kind == "invoice_payment"`. `checkout.session.completed`
(and `payment_intent.succeeded` as a fallback) now branches on that metadata
key before falling through to the pre-existing subscription-checkout path, so
a shop's customer invoice and HarborIQ's own subscription billing can never be
confused for one another even though they arrive on the same webhook
endpoint. The new branch, `_on_invoice_payment_completed`, resolves the
invoice by whichever Stripe id is present, row-locks it, computes
`amount_paid` (clamped to `total`), lands on `paid` or `partial` via
`InvoiceSM.assert_transition`, and inserts a `payments` row — all guarded by
the existing `stripe_processed_events` idempotency table, so a duplicate
delivery of the same `event.id` is a no-op rather than a double payment.

**Tenant-safe foreign keys close the same hole CRM closed in migration 0003.**
`estimates` didn't yet have `UNIQUE (company_id, id)` (invoices already did,
reserved in 0003 for this phase); migration 0004 adds it, then rewrites
`estimates.job_id`/`customer_id`, `invoices.estimate_id`/`customer_id`, and
`payments.invoice_id` as composite `(company_id, <id>)` foreign keys.
`job_line_items.invoice_id` already got its composite FK in 0003 — this phase
is simply the first one that writes to it, and 0004 only adds the supporting
index. `tests/test_invoicing_rls.py` proves both halves of the guarantee:
RLS blocks the read, and even a query that bypasses RLS (an FK check) cannot
represent a cross-tenant reference in the first place.

**Deferred, on purpose (fixed in Phase 8 — see "Billing operations" below):**
- ~~Stripe Connect (per-tenant merchant-of-record) onboarding~~ — shipped.
- ~~Refunds and partial refunds~~ — shipped.
- ~~PDF invoice generation and email delivery of the pay link~~ — shipped.
- ~~Automated overdue/dunning reminders against `due_date`~~ — shipped.
- The React customer-facing pay page — the API is ready, there's no frontend
  yet in this repo. Still deferred; see "What's intentionally NOT here yet".

## Payment architecture

Two Stripe surfaces exist in this codebase and must not be conflated:

1. **HarborIQ's own SaaS subscription billing** (a marine shop paying
   HarborIQ) — `subscriptions`/`subscription_plans`, driven by Stripe Billing
   `invoice.payment_succeeded` / `invoice.payment_failed`. Handling here is
   still a stub (`_on_subscription_payment_succeeded`) pending Phase 4.
2. **A marine shop's customer paying their invoice** (this phase) — a Stripe
   Checkout Session created against the platform's own Stripe account,
   identified by `metadata.kind == "invoice_payment"` on
   `checkout.session.completed`. `app/services/stripe_billing.py` is
   intentionally thin: it degrades to `None` on any Stripe error or missing
   API key rather than ever raising, so a Stripe outage cannot block sending
   an invoice or take down the pay page.

**Stripe Connect shipped in Phase 8** for (2), using Standard accounts and
the **direct charge** pattern: once a tenant completes onboarding
(`companies.stripe_connect_account_id` is set), `create_checkout_session`
passes `stripe_account=<connect_id>` so the Checkout Session — and the
resulting charge — is created directly on the *connected* account. The
tenant is the merchant of record and Stripe settles funds straight to them;
HarborIQ is not in the money-movement path for that transaction. A tenant
that has not connected (or whose Connect API call fails) transparently
falls back to the pre-existing single-platform-account Checkout Session —
`send_invoice` never blocks on Connect status, matching the existing
"Stripe outage cannot stop sending an invoice" guarantee. See "Billing
operations" below for the onboarding flow itself.

**Destination charges / `application_fee_amount` (HarborIQ taking a
platform fee out of each connected-account charge) are explicitly deferred**
— this phase ships direct charges only, where 100% of the charge belongs to
the tenant and HarborIQ's own revenue comes solely from SaaS subscription
billing (surface 1 above), not a take rate on customer payments. Adding a
platform fee later is a config/parameter change to the same Checkout Session
call (`application_fee_amount` + a destination on the charge), not a data
model or architecture change — but it is a pricing/legal decision (what fee,
disclosed how, in which tenant agreement) that deliberately was not made
here. **The final merchant-of-record and fee model still requires
legal/payment-provider review** — do not treat this scaffold as legal advice.
See the corrected build spec, §8.

## Crypto payment rail (Phase 18)

Phase 18 adds an optional stablecoin invoice-payment rail that uses a
**licensed payment processor (Stripe), not HarborIQ on-chain custody**:
HarborIQ never holds wallet keys, accepts a customer transfer directly, or
settles blockchain assets. `POST /invoices/{id}/crypto-payment-intent`
records a pending `crypto_payments` row and asks the provider for a hosted
Checkout URL; Stripe's signed outcome then reaches `POST /webhooks/crypto`.
The confirmed path reuses `invoices.mark_paid_from_webhook` rather than
forking invoice arithmetic or `InvoiceSM` transitions, so partial and full
payments retain the same row-locking/clamping protections as card Checkout.

The rail is **off by default** (`CRYPTO_PAYMENTS_ENABLED=false`). Going live
requires a Stripe account for which Stripe has enabled stablecoin/crypto
payments, `STRIPE_API_KEY`, and a strong `CRYPTO_WEBHOOK_SECRET`. The webhook
verifies an HMAC-SHA256 digest against the raw body whenever that secret is
present; without it, development accepts a locally generated event with a
warning, while every non-development environment fail-closes with 503. Its
`crypto_processed_events` deduplication record is inserted in the same
transaction as the crypto-payment status/invoice update, so replaying a
provider event cannot double-pay an invoice. Migration `0020` adds
`crypto_payments` (tenant RLS plus a cross-tenant-safe composite invoice FK)
and the service-role `crypto_processed_events` audit/dedup table.

## Billing operations (Phase 8)

Four previously-deferred billing gaps close this phase: Stripe Connect
onboarding, refunds, PDF/email invoice delivery, and dunning — plus a new
AR aging report. All of it is additive to the invoicing lifecycle above;
nothing about `InvoiceSM`'s core `draft -> sent -> paid` path changed.

**Stripe Connect onboarding** (`app/services/billing.py`,
`app/api/v1/routes/billing.py`) is two endpoints behind `require_admin`:
`POST /billing/connect/onboarding-link` creates a Standard Connect account
(reusing `companies.stripe_connect_account_id` if onboarding was started but
never finished, rather than minting a duplicate account on every retry) and
returns a fresh Stripe-hosted onboarding URL; `GET /billing/connect/status`
reports `connected`/`charges_enabled`/`details_submitted` for the settings
page. Both degrade honestly instead of erroring the page: no account on file
is a normal `connected: false`, and an unreachable Stripe with an account id
already on file reports `charges_enabled: false` rather than 500ing.

**Refunds** (`app/services/invoices.py::refund_invoice`,
`POST /invoices/{id}/refund`, `require_operations`) row-locks the invoice,
validates the requested amount against `amount_paid - already_refunded`
(over-refunding is a 409, not a partial success), calls
`stripe_billing.create_refund` — passing the tenant's Connect account id
when the original charge was a direct charge, otherwise the platform
account — and lands the invoice on `refunded` (amount == full `amount_paid`)
or `partially_refunded` (anything less) via `InvoiceSM.assert_transition`.
A new `refunds` table (migration 0007) records every refund — amount,
reason, Stripe refund id, who issued it — as an audit trail separate from
the `payments` table that only ever records money coming in.

**PDF generation + email delivery** (`app/services/invoice_pdf.py`,
`app/services/invoice_render.py`) finally consumes the `invoice.send` outbox
event that every phase since invoicing shipped has queued but nothing read:
the outbox consumer now renders the invoice (line items, totals, pay link)
to a PDF with **reportlab** (chosen over weasyprint specifically to avoid
its native pango/cairo/gdk-pixbuf dependency chain, which is not guaranteed
present on every deploy target — reportlab is pure-Python + Pillow and
`pip install`s identically everywhere) and attaches it to the same
email-delivery path `app/services/email.py` already uses for password
resets and invites (SMTP if configured, console fallback otherwise) —
no new transport, just a new caller. `pypdf` is a dev/test-only dependency
used to read the generated bytes back and assert on their contents in
`tests/test_invoice_pdf_email.py`; it is not used at runtime.

**Dunning** (`app/jobs/dunning_sweep.py`, `app/services/billing.py`) finds
invoices in `sent`/`partial` status past `due_date` with `balance_due > 0`,
respects a 3-day `DUNNING_REMINDER_COOLDOWN_DAYS` cooldown tracked in the
new `invoices.last_reminder_sent_at` column (so a tight cron schedule cannot
spam a customer who already got a reminder this week), and queues a reminder
email through the existing outbox rather than sending directly — the same
claim/retry/dead-letter machinery as every other outbound email. Exposed as
both `POST /billing/dunning/run` (on-demand, per-tenant, `require_admin`)
and a standalone `app/jobs/dunning_sweep.py` script loopable over every
company. **Update (Phase 17):** the sweep also now runs automatically —
`app/core/celery_app.py`'s `dunning-sweep-hourly` beat schedule calls
`app.tasks.sweep_tasks.dunning_sweep_task` on its own, so a tight manual
cron/loop is no longer required to keep reminders flowing.

**AR aging** (`GET /reports/ar-aging`, `require_operations`) buckets every
customer's outstanding `balance_due` into 1-30 / 31-60 / 61-90 / 90+ days
past due (relative to `due_date`), returning per-customer rows plus bucket
and grand totals — the read-only report a shop's office staff needs to know
who to chase first, without exporting invoices to a spreadsheet to compute
it by hand.

**Deferred, on purpose (this phase):**
- Destination charges / `application_fee_amount` platform-fee revenue on
  top of Connect — direct charges only; see "Payment architecture" above.

**Shipped in a later phase (Phase 17), no longer deferred:**
- A scheduled runner for the dunning sweep — see the "Update (Phase 17)"
  note above.
- Refund webhooks (`charge.refunded` arriving asynchronously from Stripe to
  reconcile a refund issued directly in the Stripe Dashboard rather than
  through this API) — `app/services/stripe_webhooks.py`'s `_on_charge_refunded`
  now handles this as a third, independent, idempotent path alongside the
  synchronous `POST /invoices/{id}/refund` flow.
- PDF export of the AR aging report — `GET /reports/ar-aging/export.pdf`
  alongside the Phase 14 CSV export; PDF was the explicitly-requested gap
  this later phase closes.

## Customer self-service portal (Phase 9)

A durable, magic-link customer portal plus a customer<->staff messaging
thread. Two access-model options were on the table; **Option A (a durable
magic link, extending the existing `public_tokens` pattern) was chosen over
Option B (a full customer password/login system)** for this phase — it is
the smallest correct thing that gets a real customer-facing surface
shipped, it reuses infrastructure that already has isolation and
expiry/revocation tests (`app/services/public_tokens.py`), and it avoids
introducing a second authentication system (separate from `users`/sessions)
for a login a customer will use rarely. See `app/services/portal.py`'s
module docstring for the full reasoning.

**How the link works.** `POST /customers/{id}/portal-invite`
(`require_operations`) issues a `public_tokens` row with the new
`purpose="portal"` value, a 2,160-hour (90-day) TTL, and a high use ceiling
(10,000) — unlike `invoice_pay`/`estimate_approve` tokens, a portal link is
meant to be opened repeatedly over months, not consumed once. Resolving it
(`GET /portal/{token}/...`) never burns a use, the same non-consuming read
pattern `GET /public/invoice/{token}` already established. The link is
emailed through the existing outbox (`customer.portal_invite` event,
console fallback in dev) — the raw token itself is never returned by the
API, matching every other `issue_public_token` caller. Calling the invite
endpoint again **renews** the link (a fresh token; the old one still works
until it separately expires) rather than erroring, so staff can always hand
out a working link.

**What the portal shows** (`app/services/portal.py`, `app/schemas/portal.py`,
`app/api/v1/routes/portal.py`): profile + vessels (`/me`), job history
with status/schedule/technician but no internal notes or cost/margin data
(`/jobs`), invoices (`/invoices`), and estimates (`/estimates`). Payment and
approval are **not reimplemented** for the portal —
`/invoices/{id}/pay-url` calls the same `get_or_create_checkout_url` the
staff-side send flow uses, and `/estimates/{id}/approve-token` mints a
fresh, single-purpose `estimate_approve` token so the portal's "Approve"
button POSTs to the exact same `POST /public/estimate/{token}/approve`
endpoint an emailed estimate link already uses — one approval code path,
two ways to reach it.

**Tenant *and* customer isolation** (the critical requirement for this
phase): every portal route resolves the token to a `(company_id,
customer_id)` pair and every downstream query is scoped to *both* — not
just the tenant. A token for customer A can never return customer B's
data even inside the same company, and every list/read query filters on
`customer_id`, not only `company_id`. `tests/test_portal_access.py` and
`tests/test_portal_data.py` assert this directly (same-company
customer-A-vs-B isolation, not just cross-company).

**Messaging** (`app/db/models.py::Message`, `app/services/messages.py`,
`app/schemas/messages.py`, `app/api/v1/routes/portal.py` +
`app/api/v1/routes/messages.py`) is a new `messages` table (migration
0008) with RLS tenant isolation like every other tenant table, a
`sender_type` of `customer`/`staff`, and an optional `job_id` (a message
can be general, not tied to one work order). Customers send/read through
`POST`/`GET /portal/{token}/messages`; staff get a **company-wide inbox**
(`GET /messages`, `unread_only` filter) as the primary surface — chosen
over an exclusively job-nested endpoint because a general message has no
job to nest under — plus a `GET /messages/by-job/{job_id}` convenience view
and `POST /messages/{id}/read`. Each direction queues a best-effort outbox
notification (`message.new_from_customer` to the shop, `message.new_from_staff`
to the customer, when an email is on file) using the same outbox
machinery as everything else in this repo — no new transport.

**Deferred, on purpose (this phase):**
- **Option B (full customer password/account system).** A durable magic
  link (Option A, above) was chosen instead — see the reasoning above and
  in `app/services/portal.py`. Revisit if customers need concurrent
  multi-device sessions with their own credentials rather than a single
  shared link, or if a link's 90-day/10,000-use ceiling ever proves
  insufficient in practice.
- **Real-time messaging (WebSockets/SSE/push notifications).** Both sides
  poll/refetch today; a new message shows up on the next page load or
  `react-query` refetch, not instantly. The outbox email is the only
  "push" that exists.
- **A Celery/cron-scheduled outbox worker for portal-invite and message
  emails.** Same precedent as every other outbox consumer in this repo
  (see `app/services/outbox.py`'s docstring and "What's intentionally NOT
  here yet" below) — dispatch runs via `BackgroundTasks` right after commit,
  not a scheduled worker.
- **Read receipts beyond staff-side "mark read."** The customer portal does
  not currently mark staff replies read on the customer's behalf, and
  there is no per-message read receipt visible to the customer.

## Team, skills & geocoding (Phase 10)

Two gaps existed going into this phase: nobody but an admin editing the
database directly could update their own name/skills/home address, and no
address on any customer/user record ever turned into a real `latitude`/
`longitude` — the Phase 7 dispatch engine's distance factor (see "AI
dispatch engine" above) always degraded to neutral as a result. Both are
closed now.

**Self-service + admin profile editing — `PATCH /api/v1/users/{id}` and
`GET /api/v1/users`.** Any authenticated user may edit their own
`full_name`, `skills`, and `address_text` via `PATCH /users/{id}` where
`{id}` is their own id. An owner/admin may edit **any** user in their own
company the same way, plus `role` and `is_active` — fields a non-admin is
explicitly forbidden from setting even on their own row (`app/services/
users.py::update_profile` raises `FieldNotPermitted`, mapped to a `403` in
the route). `password_hash`/`mfa_secret_enc` are deliberately untouchable
here — they keep their own dedicated flows (login, password reset).
Tenant isolation is enforced the same way as everywhere else in this
codebase: a user id outside the caller's company resolves to `404`, not
`403`, so existence cannot be inferred cross-tenant. `GET /users` (any
authenticated `require_operations` role — owner/admin/office) returns the
full roster: name, email, role, active status, skills, address text, and
whether home coordinates are geocoded — the data source for the new
frontend team page below.

**Geocoding — OpenStreetMap Nominatim.** `app/services/geocoding.py`
exposes one function, `geocode(address: str) -> tuple[Decimal, Decimal] |
None`, backed by `https://nominatim.openstreetmap.org/search`: free, no
API key, but rate-limited to 1 request/second and required by Nominatim's
usage policy to send a descriptive `User-Agent`. A minimal in-process
rate limiter (`time.monotonic` + `time.sleep`, no Redis needed at this
call volume — geocoding only happens on an admin/user save or the
backfill job, not on high-volume traffic) enforces the 1 req/s floor.
**Swap point, documented in code:** `geocode()` is the single seam every
caller goes through; replacing Nominatim with Google Maps/Mapbox later is
a rewrite of this one file's internals only (parse a different JSON
shape, add an API key header/param) — no caller in `app/services/
users.py`, `app/services/customers.py`, or `app/jobs/geocode_backfill.py`
changes. Look for the `# SWAP POINT` comment in `app/services/
geocoding.py` for exactly where that would happen.

**Graceful degradation everywhere geocoding is wired in — the
non-negotiable rule for this phase.** A geocoding failure (no match,
timeout, non-200, malformed response, or any unexpected exception) never
blocks the save it's attached to: the address text still saves, and
`latitude`/`longitude` are simply left `null`, consistent with how the
dispatch engine's distance factor already treated missing coordinates
before this phase existed. This is wired into:
- `PATCH /users/{id}` — editing/setting `address_text` (self or admin)
  geocodes it into `home_latitude`/`home_longitude`.
- `POST /customers` and `PATCH /customers/{id}` — creating a customer with
  an address, or changing any of `address_line1`/`city`/`state`/
  `postal_code`/`country` on an existing one, re-geocodes from the merged
  address fields (`app/services/customers.py::_geocode_address`).
- Company address geocoding is **explicitly out of scope this phase** —
  see "Deferred, on purpose" below; there is no address-text field or
  settings route for `Company` anywhere in the codebase today for
  geocoding to hang off of.

**Backfill — `POST /api/v1/admin/geocode-backfill` and
`python -m app.jobs.geocode_backfill`.** Phases 6-9 created seed/test data
with addresses and no coordinates (geocoding was explicitly deferred until
now — see the old "AI dispatch engine" deferred-list entry, now removed).
`app/jobs/geocode_backfill.py` provides `backfill_customers`,
`backfill_users`, and `backfill_company` (both, scoped to one company) —
all idempotent by default: only rows with an address **and** null
coordinates are touched, so running it twice does not re-geocode
already-set rows unless `force=True`/`--force` is passed. The route is
`require_admin`-scoped to the caller's own company; the module's
`run(force=False)` entry point (and its `if __name__ == "__main__":` CLI,
run as `python -m app.jobs.geocode_backfill [--force]`) iterates every
company in the database, for an operator who wants a one-shot sweep
across all tenants rather than per-company via the API.

**Team roster page — `/team` (frontend).** Viewing the roster is
`require_operations`-equivalent (owner/admin/office), matching `GET
/users`'s gate; editing someone **else's** profile is admin-only,
matching `PATCH /users/{id}`'s server-side rule — both enforced again in
the React route guard and nav link (`canManageOperations`/
`canManageUsers` in `AuthContext.tsx`), not just trusted client-side.
Every row shows name, email, role, skills, address text, a
located/not-located badge, and active status; an "Edit" action opens a
modal that is either a self-edit (name/skills/address only) or, for an
admin editing a teammate, the same fields plus role/active-status. The
prior invite-only flow (`POST /auth/invites`) is preserved on the same
page — it remains the only way to add a new teammate; Phase 10 adds
editing, not provisioning.

**Deferred, on purpose (this phase):**
- **Company address/geocoding.** No `address_text` field or settings
  route exists for `Company` anywhere in this codebase — adding one was
  out of scope for this phase, which focused on the two records that
  already had a natural home for a free-text address (`User`, `Customer`).
  The backfill job's `run()` only reads `companies` to enumerate
  `company_id`s to iterate customers/users by; it never geocodes a
  company's own address.
- **A normalized address (street/city/state/zip) field on `User`** —
  `address_text` is a single free-text column (MVP-sufficient for
  Nominatim, which accepts a single query string), not structured like
  `Customer`'s `address_line1`/`city`/`state`/`postal_code`/`country`.
- **Google Maps/Mapbox geocoding** — Nominatim was chosen because no
  Google Maps/Mapbox connector is currently connected for this workspace
  and it needs no API key; the swap point is documented above and in
  `app/services/geocoding.py` for whenever better accuracy/higher rate
  limits are worth a paid provider.
- **A background/scheduled geocoding queue** — geocoding happens
  synchronously, inline with the triggering `PATCH`/`POST` request (and
  the 1 req/s rate limiter means a save with a new address adds up to ~1s
  of latency). Fine at this request volume; a queue (Celery/RQ) would be
  the upgrade if geocoding ever needs to happen off the request path.

## Live dispatch board, map & SMS (Phase 11)

Two gaps existed going into this phase: dispatching was a ranked list with no
visual/spatial context, and there was no way for the shop or a customer to
reach each other by text. Both are closed now, following the exact
precedent already established in this repo: reuse existing infrastructure
(the Phase 7 assignment endpoint, the Phase 9 `messages` table) rather than
building a parallel path, and gracefully degrade to a console/log transport
when no real provider is configured — the same trade-off already made for
SMTP.

**Live technician location — honest scope.** `POST
/api/v1/users/me/location-ping` lets any authenticated user record their own
`{latitude, longitude}` (never someone else's — there is no `user_id` in the
request body; it always comes from the auth token). The frontend
(`frontend/src/hooks/useLocationPing.ts`) calls this every 3 minutes for
technician-role users only, using the browser's Geolocation API, while the
staff web app tab is open and the user has granted location permission.
**This is best-effort, not background tracking:** closing the tab, closing
the browser, or the device sleeping stops pings immediately, and there is no
mobile app yet to keep pinging from a phone in a pocket. `GET
/api/v1/users/technician-locations` (`require_operations`, same gate as the
team roster) returns every technician's best-known position — the live ping
if one exists (`is_live=true`), otherwise a static fallback to their
Phase 10 geocoded home address (`is_live=false`) so the map is never simply
blank for a technician who hasn't opened the app today. **True
background/mobile location tracking that keeps working with the app closed
is deliberately out of scope here — that is Phase 12** (the offline-capable
mobile field app), which is the only place a real background-location
primitive (a native app, or a PWA with a service worker and the
background-geolocation APIs mobile OSes require for that) belongs.

**Dispatch board — `/dispatch` (frontend).** A visual, drag-and-drop board
replacing the ranked list as the primary day-to-day assignment surface: one
column per active technician plus an "Unassigned" column, native HTML5 drag-
and-drop (no extra DnD library dependency). Dropping a job on a technician's
column calls the exact same `POST /api/v1/jobs/{id}/assign` endpoint the
existing `DispatchSuggestions` ranked-candidates list on `JobDetailPage`
already calls — `DispatchSuggestions` itself was left untouched, so there
are now two UIs reaching one assignment code path, matching the precedent
the customer portal set for invoice-pay/estimate-approve reuse in Phase 9.
Assigning a job from the board also queues the same job-confirmation SMS
described below.

**Map — Leaflet + OpenStreetMap, free, no API key.** `DispatchMap.tsx`
renders underneath the board using `react-leaflet` against OpenStreetMap's
free tile servers — no API key, no billing account, consistent with the
Nominatim geocoding choice already made in Phase 10 (same free-OSM-ecosystem
reasoning; see "Team, skills & geocoding" above). It plots technician
markers (live-ping vs. home-base fallback, visually distinguished) and
job/customer markers (reusing the `Customer.latitude`/`longitude` Phase 10
already geocodes — no new backend geocoding call needed). Default map
center is Sarasota/Bradenton, FL, matching where this pilot's first tenant
operates. Marker icon images are pulled from the `unpkg.com` CDN rather than
bundled, because Vite does not automatically resolve Leaflet's default
marker image asset paths.

**Two-way SMS — console-fallback graceful degradation, exactly mirroring
SMTP.** `app/services/sms.py::send_sms` mirrors `app/services/email.py`'s
exact shape: `is_configured()` is `True` only once all three of
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` are set;
when any is missing (the default in this workspace — no Twilio account is
connected here), every outbound SMS logs the destination and a truncated
body at INFO instead of sending, so a contributor can exercise every SMS-
triggering flow without a real Twilio account, the same as password-reset/
invite emails without a real mailbox. When configured, `send_sms` POSTs
directly to the Twilio REST API (`https://api.twilio.com/2010-04-01/
Accounts/{sid}/Messages.json`) via `httpx` with HTTP Basic auth —
deliberately **not** the `twilio` PyPI SDK, since sending one SMS is a
single POST and `httpx` is already a dependency; a full SDK would be new
weight for a provider not even configured yet. Any HTTP/network failure is
caught and logged, never raised, so a transport failure can never roll back
the business transaction that already committed — the same reasoning
`outbox.dispatch_pending` already documents for email.

**Outbound triggers.** Two events reuse the existing outbox pattern (new
`sms.send` event type, consumed by `outbox.dispatch_pending` alongside the
existing email event types): a job-confirmation text queued when a job is
assigned to a technician (`POST /jobs/{id}/assign`, extended this phase),
and an "on my way" text via the new `POST /api/v1/jobs/{id}/notify-on-my-way`
(same authorization as moving a job's status — office staff for any job,
the assigned technician for their own job). Both are best-effort: a customer
with no phone number on file is a silent no-op, not an error, since that
reflects the shop's own data rather than a mistake by the caller.

**Inbound webhook — `POST /api/v1/webhooks/sms/inbound`.** Public,
unauthenticated (like the Stripe webhook), Twilio-shaped: reads `From`/
`Body` from the standard form-encoded POST Twilio sends on every inbound
SMS/MMS. **Register `{APP_BASE_URL}/api/v1/webhooks/sms/inbound`** as the
"A message comes in" webhook on the shop's Twilio phone number once real
credentials exist. Signature verification (`X-Twilio-Signature`, HMAC-SHA1
over the URL + sorted form params, the standard Twilio validation scheme) is
enforced only once `TWILIO_AUTH_TOKEN` is configured — exactly the same
shape of trade-off `app/api/v1/routes/stripe_webhooks.py`'s Stripe webhook
already documents for `Stripe-Signature`: hard-failing every request with no way to
configure a secret would make the endpoint untestable and would not protect
anything today. An inbound message matched to a customer by phone number
lands in the exact same Phase 9 `messages` table the customer portal and
staff inbox already use, tagged `channel="sms"` (migration `0010` adds this
column, `NOT NULL DEFAULT 'portal'` so every pre-Phase-11 message is
correctly backfilled as portal traffic); it shows up in the existing staff
`GET /messages` inbox with no separate "SMS inbox" UI. A staff reply
(`POST /messages`) is routed back out over SMS instead of email when the
customer's most recent inbound message on that thread was itself SMS —
otherwise it behaves exactly as it did before this phase.

**Phone-matching simplification — documented, not hidden.** Customer-phone
resolution for inbound SMS (`app/services/sms_webhooks.py::
_find_customer_by_phone`) matches globally across **all** tenants by phone
number, not per-tenant Twilio-number routing. That is the honest scope for
a workspace with a single (unconfigured) Twilio number: there is no second
Toll-Free/local number per company yet to route an inbound text to the
correct tenant by *which* Twilio number received it, so the match is by the
customer's phone number alone. **This becomes a real gap the moment two
tenants share an overlapping customer phone number or once this platform
onboards more than one paying tenant with its own Twilio number** — the
fix is routing inbound webhooks by the `To` field (the shop's own Twilio
number) once every tenant has a dedicated number, which is a Twilio
account/billing decision as much as a code change, and was out of scope
for this phase.

**Deferred, on purpose (this phase):**
- **True background/mobile location tracking.** Location pings only happen
  while a technician has the staff web app open in a foreground browser tab
  with location permission granted — see the honest-scope note above.
  Deferred to Phase 12 (the offline-capable mobile field app).
- **Per-tenant Twilio number routing for inbound SMS.** Customers are
  matched globally by phone number across all tenants, not routed by which
  Twilio number received the text — see the phone-matching simplification
  above. Revisit once more than one tenant needs its own Twilio number.
- **Outbound MMS / rich media.** Only plain-text SMS bodies are sent;
  Twilio's `MediaUrl` inbound fields are ignored by the webhook today.
- **A calendar/time-grid view on the dispatch board.** This phase ships the
  column-per-technician kanban-style board; a true calendar/Gantt hybrid
  (jobs laid out against a time axis, not just a status column) remains a
  future iteration of the same `/dispatch` page.
- **Real-time board/map updates (WebSockets/SSE).** The board and map
  refetch on an interval (`react-query`, 60s for technician locations) and
  on manual actions, not via a live socket — the same trade-off already
  made for the customer portal's messaging in Phase 9.

See `docs/COMPETITIVE_PARITY_ROADMAP.md`'s Phase 11 entry for how this maps
to ServiceTitan's dispatch board as the competitive parity target.

## Offline-first mobile field app (Phase 12)

Phase 11 explicitly deferred true offline/background field capability to
"whichever comes first: a native app or a PWA with a service worker." This
phase picks the PWA path and closes that gap: technicians get an
installable, offline-first mobile experience without anyone needing an
Apple Developer account, App Store review, or a Google Play listing.

**Why a PWA and not a native app.** A true native iOS/Android app is
explicitly **out of scope** for this phase and was not attempted — it
requires the operator's own Apple Developer Program membership ($99/yr) and
Google Play Console account, plus app-store review cycles, neither of which
this workspace has or can provision on someone else's behalf. A PWA gets
real offline capability, a home-screen icon, and a standalone (no browser
chrome) full-screen window on iPhone via Safari's "Add to Home Screen" —
with zero app-store dependency. The trade-off, honestly stated: iOS Safari's
PWA support is real but constrained versus native (background sync only
fires on the `online` event while the app has been opened recently, not a
true OS-level background task; push notifications on iOS PWAs need iOS
16.4+ and the user must have already added the app to their home screen).
That trade-off is acceptable for this phase's scope — offline job caching,
an offline action queue, photo/signature capture, and time clock — none of
which need a true background task, only "works while the app is open,
survives a dropped connection, and syncs when connectivity returns."

**Installable app shell — `vite-plugin-pwa`.** `frontend/vite.config.ts`
adds the plugin in `generateSW` mode: it emits a web app manifest
(`manifest.webmanifest` — name, theme color `#7e14ff`, `display:
"standalone"`, `start_url: "/field"`) and a Workbox-generated service worker
(`sw.js`) that precaches the app shell (JS/CSS/HTML — 17 entries, ~600 KiB)
so the app itself loads offline, not just previously-viewed data.
Critically, **API responses are never cached by the service worker** — the
runtime caching rule for any `/api/` path is `NetworkOnly`, on purpose:
IndexedDB (below), not the HTTP cache, is the single source of truth for
offline job data, so there is exactly one place a contributor needs to look
for "what does the technician see when offline," not two caches that can
disagree. `index.html` adds the three meta/link tags iOS Safari actually
reads (`apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`,
`apple-touch-icon`) — the web app manifest alone is largely ignored by iOS.

**IndexedDB job cache — `frontend/src/lib/offlineDb.ts`.** A small,
dependency-free wrapper around the browser's IndexedDB (no `idb`/`dexie`
dependency added — the schema is two stores and does not need a query
layer): `cached_jobs` (keyed by job id) and `pending_actions` (keyed by
idempotency key, see below). `frontend/src/hooks/useFieldJobs.ts` fetches
the technician's jobs from the network, writes a fresh copy to
`cached_jobs` on every successful load, and — this is the offline path —
falls back to whatever is already cached when the network fetch fails,
surfacing a `fromCache: true` flag the UI uses to show an honest
"showing cached data" banner rather than silently presenting stale data as
live.

**Offline action queue (outbox) — `frontend/src/lib/offlineQueue.ts`.**
Every field action a technician takes while potentially offline (clock in,
clock out, add a photo/signature attachment) is first written to the
`pending_actions` IndexedDB store, then replayed against the real API as
soon as a send succeeds. This deliberately mirrors the backend's own outbox
pattern already used for email/SMS dispatch (see "Auth hardening" and
"Live dispatch board, map & SMS" above) — same idea, client-side: never
lose an action to a dropped connection, and make retrying safe. Replay is
strictly in-order (oldest action first) and **halts at the first failure**
rather than skipping ahead — a clock-out must never reach the server before
an earlier clock-in that is still stuck offline, since the backend's
one-open-entry-per-technician-per-job constraint (migration `0011`'s
`uq_job_time_entries_one_open_per_tech_job`) depends on entries arriving in
the order they actually happened. `frontend/src/hooks/useOfflineQueue.ts`
is the React binding: it auto-replays on mount and again on the browser's
`online` event, exposing `pendingCount` so the UI can show "3 actions
waiting to sync."

**Idempotency keys — the mechanism that makes retries safe.** Every queued
action carries a client-generated `idempotencyKey` (`crypto.randomUUID()`,
minted once at enqueue time and never regenerated on retry —
`newIdempotencyKey()` in `offlineQueue.ts`). The backend's migration `0011`
adds unique partial indexes on `(company_id, idempotency_key)` for both
`job_attachments` and `job_time_entries`; `app/services/field_app.py`'s
`add_attachment`/`clock_in`/`clock_out` all check for an existing row with
that key first and **return the existing row instead of erroring or
inserting a duplicate**. That is what makes it safe for the client to blindly
resend an action it is unsure actually landed (e.g. the request succeeded
server-side but the response was lost before the client saw it, a common
real-world case on a flaky marine-yard Wi-Fi connection): the same key
always resolves to the same row, however many times it is sent.

**Field view — `/field` and `/field/:id` (`frontend/src/pages/FieldPage.tsx`).**
A separate, deliberately minimal route tree from the main `AppShell` admin
UI (added as its own top-level `ProtectedRoute` block in `App.tsx`, not
nested inside `AppShell`) — this is the view a technician actually uses in
the field, not the office/admin dashboard shrunk down. `/field` lists the
signed-in technician's own upcoming jobs (`technician_id` filtered
client-side against the already-fetched job list — no new backend endpoint
was needed), sorted by scheduled time, excluding completed/canceled jobs.
`/field/:id` is the per-job action screen: clock in/out buttons, a photo
capture input (`<input type="file" accept="image/*" capture="environment">`,
which opens the rear camera directly on a phone rather than a generic file
picker), and a signature pad. Every one of those three actions is enqueued
through `useOfflineQueue` — there is no code path in the field view that
calls the API directly, so "works offline" is not a special case bolted on,
it is the only way these actions are ever sent.

**Signature capture — `frontend/src/components/SignaturePad.tsx`.** A plain
HTML5 `<canvas>` (no signature-pad library dependency), using Pointer Events
(not separate mouse/touch handlers) so the same code path handles a
technician's finger on an iPhone and a mouse in a desktop browser. "Save"
is disabled until at least one stroke has been drawn, and exports
`canvas.toDataURL("image/png")` — a base64 PNG data URL — which is enqueued
as a `kind: "signature"` attachment.

**Storage — base64-in-Postgres, honestly an MVP choice.** Both photo and
signature attachments are stored as base64-encoded bytes directly in the
`job_attachments` table (migration `0011`), not in S3/object storage. This
was the pragmatic choice for this phase's scope (no object-storage
credentials exist in this workspace, and the volume of attachments a single
marine service company generates does not yet justify the added
infrastructure), but it does not paint the schema into a corner: the table
already carries an unused `storage_path` column reserved for a future
migration-free cutover to S3/R2/GCS — the day it is needed, a backfill job
can move existing rows out of Postgres and populate `storage_path`, and new
writes can switch to it, without an ALTER TABLE. This is the same
"documented, not hidden" MVP-storage trade-off pattern already used
elsewhere in this repo (e.g. the in-process rate limiter ahead of a future
Redis-backed one — see "Auth hardening" above).

**Install prompt — `frontend/src/components/InstallAppBanner.tsx` and
`frontend/src/hooks/useInstallPrompt.ts`.** A dismissible banner (dismissal
remembered in `localStorage`) that adapts to the browser: Chrome/Android
fires a real `beforeinstallprompt` event the hook listens for, so the
banner can show a one-tap "Install" button; iOS Safari fires no such event
(there is no programmatic install API on iOS), so the banner instead shows
the manual steps — see "Installing on an iPhone" below.

**Installing on an iPhone (no App Store account needed):**
1. Open the HarborIQ web app URL in **Safari** (must be Safari — Chrome/
   Firefox on iOS cannot install PWAs to the home screen because they are
   required by Apple to use Safari's underlying WebKit but not its
   install UI).
2. Tap the **Share** icon (square with an arrow pointing up) in Safari's
   toolbar.
3. Scroll down and tap **"Add to Home Screen."**
4. Confirm the name ("HarborIQ") and tap **"Add."**
5. The HarborIQ icon now appears on the home screen like any other app; 
   opening it launches in a standalone window (no Safari address bar/tabs),
   starting on the technician's `/field` job list.

**Deferred, on purpose (this phase):**
- **A true native App Store / Play Store app.** Requires the operator's own
  Apple Developer Program and Google Play Console accounts — not something
  obtainable inside this workspace on the user's behalf. The PWA above is
  the full extent of "installable mobile app" for this phase.
- **True background location tracking from the field app.** Phase 11's
  README already flagged this as the reason Phase 12 exists; this phase
  shipped the PWA shell, offline queue, and field-capture features, but did
  **not** wire `useLocationPing` into the new `/field` view or add a
  service-worker background-sync-based location beacon. The existing
  foreground-tab location ping (Phase 11) still only works from the main
  staff web app. Revisit as a follow-up now that the PWA shell exists to
  host it.
- **Push notifications.** iOS 16.4+ supports web push for installed PWAs,
  but it requires a VAPID keypair, a push subscription endpoint, and a
  notification-sending path on the backend — none of which were in this
  phase's scope. The install banner and offline-sync UI are the only
  "the app got your attention" mechanisms today.
- **Video/voice-note attachments.** Only photo (via `<input
  capture="environment">`) and canvas-drawn signature attachments are
  implemented, matching this phase's actual spec — an earlier roadmap stub
  mentioned richer media capture, but photo + signature + time clock is the
  scope that was actually built and tested here.
- **True live-ticking "still clocked in" duration.** `JobDetailPage`'s
  admin-side time-entry table computes the elapsed duration for an open
  (not-yet-clocked-out) entry once, at render/mount time, rather than
  ticking a live clock — a deliberate simplicity trade-off (calling
  `Date.now()` on every render is flagged by React's render-purity rules
  and would need a `setInterval`-driven re-render to tick live, which is
  more machinery than a staff-side summary table needs).
- **Conflict resolution beyond "first write wins."** If the same job is
  edited from both the admin UI and updated in a technician's stale
  IndexedDB cache while offline, the queued action is simply replayed once
  connectivity returns with no diff/merge step — acceptable for this
  phase's action types (clock events and attachments are append-only, not
  edits to a shared mutable field, so there is no real conflict to resolve
  yet), but would need real thought if a future phase adds an offline-
  editable mutable field.

See `docs/COMPETITIVE_PARITY_ROADMAP.md`'s Phase 12 entry for how this maps
to ServiceTitan/Jobber's native mobile technician apps as the competitive
parity target.

## Inventory, parts & vendors (Phase 13)

Phase 7's dispatch engine shipped a `parts_availability` scoring factor that
was, by design, a **permanent documented no-op** — there was no linkage
between a job's parts and real stock levels to score against, so it always
returned neutral. This phase closes that gap: real inventory CRUD, SKU/
barcode-style lookup, vendors, a draft/submit/receive purchase-order
lifecycle with correctly guarded `quantity_on_hand` writes, low-stock reorder
suggestions with one-click *draft* PO generation, and — the payoff — wiring
all of it into the dispatch scorer so `parts_availability` is now a real
signal instead of a reserved weight.

**Migration `0012_inventory_procurement`.** Three changes: a partial unique
index `uq_inventory_items_company_sku ON inventory_items (company_id, sku)
WHERE sku IS NOT NULL` (SKU stays optional, but if two items in the same
company both have one, it must be unique — the same rule a real barcode/UPC
would enforce, and required for `GET /inventory/lookup?sku=...` to be
unambiguous); a new `vendors` table (own RLS policy, same tenant-isolation
pattern as every other table since migration 0001) plus a nullable
`inventory_items.default_vendor_id` FK added after `vendors` exists; and
`purchase_orders` / `purchase_order_line_items` — status is a Postgres enum
(`draft`, `submitted`, `received`, `cancelled`), line items carry both
`quantity_ordered` and `quantity_received` with a `CHECK
(quantity_received <= quantity_ordered)` at the database level (belt-and-
suspenders under the application-level guard below), and the line-items
table uses the same composite-FK-to-`(company_id, id)` pattern established
for `job_attachments` in migration 0011 so a line item can never reference a
purchase order belonging to a different tenant even if application logic
had a bug. Verified by dropping and recreating the database and reapplying
migrations `0001`–`0012` from scratch during this phase's work, not just
applied incrementally on top of already-migrated state.

**Two schema quirks worth knowing about, both intentional:** `inventory_items`
has no `updated_at` column — it predates `TimestampMixin` gaining one and
was never backfilled, so `app/services/inventory.py::update()` does not
attempt to set one (a raw SQL `UPDATE ... SET updated_at = now()` would
simply fail against this table); and `InventoryItemOut` exposes a `currency`
field sourced from the existing `money_currency` enum column (always `"USD"`
today, same single-currency assumption as invoicing) even though no
migration added a dedicated currency column for inventory — it reuses the
column the money-math work already put in place rather than adding a
redundant one.

**`app/services/inventory.py` extensions — CRUD, lookup, reorder
suggestions.** `create`, `get`, `list_items` (search + `low_stock_only`
filter + pagination), `update`, and `lookup_by_sku` are added alongside the
pre-existing `use_inventory_part_atomic` (unchanged — still the one
`FOR UPDATE`-guarded writer of `quantity_on_hand`; this phase does not
introduce a second, competing writer for that column). A newly created item
always starts at `quantity_on_hand = 0`: receiving stock is a purchase-order
event, not a field on the create form, so there is exactly one code path
("receive a PO line") that increases stock, matching the existing
one-code-path discipline the atomic decrement already established for
decreasing it. `reorder_suggestions` returns every item where
`quantity_on_hand <= reorder_point`, each annotated with its
`default_vendor_id` so the frontend can group suggestions by vendor.

**Vendors — plain CRUD, `app/services/vendors.py`.** Create/get/list
(search)/update. No delete: a vendor referenced by a historical purchase
order should never disappear and orphan that PO's `vendor_id` FK, so, same
as customers and technicians elsewhere in this codebase, vendors are
deactivated rather than deleted — there is intentionally no
`DELETE /vendors/{id}` route. As of Phase 17, "deactivated by convention"
became a real `is_active` flag: `POST /vendors/{id}/status` archives or
reactivates a vendor, the default `GET /vendors` list and the reorder-
suggestions-to-draft-PO flow only ever offer active vendors, and
`_require_active_vendor` in `app/services/purchase_orders.py` refuses to
draft a NEW purchase order against an archived one — but `GET
/vendors/{id}` keeps resolving an archived vendor unconditionally so a
historical PO can still render who it was actually placed with. See
"Phase 17" below.

**Purchase orders — state-machine-guarded lifecycle,
`app/services/purchase_orders.py` + `app/services/state_machines.py`
(`PurchaseOrderSM`).** `draft → {submitted, cancelled}`,
`submitted → {received, cancelled}`, `received`/`cancelled` are terminal —
mirroring the existing `JobSM`/`InvoiceSM` convention of "a completed
money/stock movement cannot be un-done by re-opening the state machine, only
by a new compensating action." Receiving is the one operation that touches
`quantity_on_hand`, and it reuses the exact `FOR UPDATE`-guarded pattern
`use_inventory_part_atomic` established in an earlier phase — the same
lock-then-check-then-write shape, just incrementing instead of decrementing,
so there remains a single family of guarded writers for that column rather
than a second, parallel implementation with its own concurrency bugs to
find. Receiving supports **partial receipt**: each line item tracks its own
`quantity_received` independently and a `POST /purchase-orders/{id}/receive`
call can cover any subset of a PO's lines in any quantity up to what's still
outstanding on that line; the PO as a whole moves to `received` once called
(matching this phase's chosen design — a single receiving event closes the
PO even if a line was only partially fulfilled, rather than modeling
"partially received" as a fifth status), while over-receiving on a single
line (asking to receive more than `quantity_ordered - quantity_received` in
one call) is rejected with a 422 and writes nothing, verified by a dedicated
concurrency/guard test.

**Reorder suggestions → one-click draft PO, but not unattended
auto-ordering — a deliberate scope boundary.** `GET
/inventory/reorder-suggestions` is read-only and side-effect-free. `POST
/inventory/reorder-suggestions/generate-po` takes a vendor and a set of
low-stock item ids and creates exactly one new purchase order in `draft`
status with a line item per selected item — nothing is submitted to a
vendor and no stock moves. A human still has to review the draft and call
`POST /purchase-orders/{id}/submit` before it means anything outside the
system. This phase deliberately does **not** implement unattended background
reordering (e.g. a Celery beat task that submits POs on a schedule once
stock crosses the reorder point) — that is a meaningfully different, higher-
trust feature (letting the system commit the business to a vendor spend
without a person in the loop) than "tell a human what's low and save them
the data entry," and conflating the two would be the kind of over-automation
this platform's AI standards explicitly warn against shipping without a
human-review step.

**SKU/barcode lookup and the `BarcodeDetector` browser-support caveat.**
`GET /inventory/lookup?sku=...` is a plain exact-match lookup — there is no
server-side barcode decoding, on purpose: decoding a barcode image is a
client-side camera concern, not something that belongs behind an API call.
`InventoryPage.tsx` feature-detects the browser's native [`BarcodeDetector`
Web API](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector)
via `"BarcodeDetector" in globalThis` and shows a manual-entry fallback with
an explicit caveat when it's unsupported, because that API's real-world
support is narrow: it works in Chrome/Edge and Chromium-based Android
browsers (Chrome for Android, Android WebView, Samsung Internet), but is
**not supported in Firefox on any platform, and not enabled by default in
Safari/Safari iOS** — WebKit has tracked it as "Under Consideration" since
2024 ([WebKit bug #254573](https://bugs.webkit.org/show_bug.cgi?id=254573))
and even recent Safari builds gate it behind a disabled-by-default
experimental flag. Concretely: an iPhone technician using Safari — the
majority mobile case for this platform's field app per the Phase 12 PWA
work — will see the manual SKU-entry fallback, not a live barcode scan, and
the UI says so rather than silently failing. Sources: [MDN's
`BarcodeDetector`
docs](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector) and
[caniuse's BarcodeDetector API
table](https://caniuse.com/mdn-api_barcodedetector) (both checked during
this phase's work).

**Dispatch engine: `parts_availability` is no longer a no-op.**
`app/services/dispatch.py::_compute_inventory_shortfall` sums each job's
`part`-kind line items by `inventory_item_id` (so two line items pulling
from the same part correctly combine into one needed-quantity check instead
of each looking individually fine) and compares against that item's current
`quantity_on_hand`. The pure `_score_parts_availability` scoring function
(still DB-free and unit-testable in isolation, same as every other factor)
then returns: full weight (10 points) if the job has no tracked part line
items at all (nothing to be blocked by); full weight if every needed part is
covered by stock; **zero** — not negative — if any part line item needs more
than is currently on hand, matching the "forfeit the credit, don't actively
penalize" shape already used for `distance` when coordinates are missing.
Both scoring entry points (`recompute_and_cache_score` for the job-level
priority queue, and `rank_technicians_for_job` for per-candidate ranking)
now call `_compute_inventory_shortfall` before scoring. **This is an
intentional planned change, not a regression:** the existing dispatch test
suite was updated this phase to assert the new real behavior (a job whose
required parts are out of stock now scores measurably lower than an
otherwise-identical job with no parts shortfall) rather than asserting the
old permanent-neutral placeholder.

**Frontend — three new pages, gated the same way "Team" already is.**
`/inventory` (search, low-stock filter with a highlighted/badged row style,
the SKU lookup form described above, and a create/edit modal with a
default-vendor dropdown), `/vendors` (list, search, create/edit modal), and
`/purchase-orders` (status-filtered list with per-row submit/cancel/receive
actions, a reorder-suggestions panel grouped by vendor with a one-click
"Draft PO" button per group that explicitly labels the result a draft — not
an auto-submitted order — and a create-PO modal with dynamic line-item
rows). All three are added to `AppShell`'s navigation and registered as
protected routes in `App.tsx` following the exact `TeamRoute` pattern:
gated behind `canManageOperations(user?.role)`, with a permission-denied
message rather than a 404 for a logged-in user who simply lacks the role.

### What's intentionally NOT here yet (Phase 13)

- **Unattended auto-reordering.** Covered above — a human must submit a
  generated draft PO; there is no scheduled/background job that submits
  purchase orders on its own.
- **Real barcode/camera decoding on unsupported browsers.** The
  `BarcodeDetector` Web API is used where the browser supports it; there is
  no JS-decoding-library fallback (e.g. a WASM barcode reader) for
  Firefox/Safari — those browsers get manual SKU entry only, this phase.
- **Multi-warehouse / multi-location inventory.** `quantity_on_hand` remains
  a single number per item per company, not per-location — fine for the
  single-shop-location assumption this platform has made since Phase 1, but
  would need a real location dimension for a multi-yard operator.
- **Vendor-side integration (EDI, vendor catalogs/pricing feeds, PO email
  delivery to the vendor).** Purchase orders live entirely inside HarborIQ;
  nothing is transmitted to the vendor automatically. A submitted PO is a
  fact the *shop* now needs to act on (call/email the vendor), not
  something the system sends on the shop's behalf yet.
## Accounting & reporting (Phase 14)

Phase 8 shipped AR aging — outstanding balances bucketed by days overdue —
but there was no revenue/cost/profitability view at all: an owner had no way
to see whether the business was actually making money in a given period.
This phase adds a pragmatic P&L and cash-flow view computed **honestly from
data that already exists** (invoices, payments, refunds, purchase orders,
technician time entries), CSV exports for every report, and a
QuickBooks-Online-importable transactions journal — deliberately **not** a
full double-entry general ledger, matching the roadmap's own reasoning that
building a real GL to compete with DockMaster's accounting suite would be
disproportionate to the value delivered.

**Migration `0013_accounting_reports`.** One change: a nullable
`users.hourly_rate NUMERIC(12,2)` column with a `CHECK
(hourly_rate IS NULL OR hourly_rate >= 0)` constraint. No pay-rate field
existed anywhere in the schema before this phase — rather than silently
inventing a labor-cost number from nothing, this phase adds the column and
makes the P&L report explicit about which technicians don't have a rate set
yet (see "labor cost, and the unavailable-not-zero rule" below). Verified by
dropping and recreating the database and reapplying migrations `0001`–`0013`
from scratch during this phase's work, not just applied incrementally on top
of already-migrated state. `hourly_rate` joins `ADMIN_ONLY_COLUMNS` in
`app/services/users.py` — same reasoning as `role`/`is_active`: a technician
should not be able to set their own pay rate via `PATCH /users/{id}`, only
an owner/admin can.

**P&L methodology — exactly what "revenue," "cost," and "labor" mean here.**
`GET /reports/pnl?start_date=&end_date=` (`require_operations`), grouped by
month plus a totals row:

- **Revenue** is **cash collected**, not accrual-invoiced value: the sum of
  `payments` rows with `status = 'succeeded'` whose `created_at` falls in
  the requested period, minus `refunds` whose `created_at` falls in the
  period. `payments` rows are written once, inside
  `invoices.mark_paid_from_webhook`, when Stripe confirms a checkout session
  — so this is genuinely "money that landed," not "invoices sent." An
  invoice issued in June but paid in July shows as July revenue, which is
  the correct cash-basis answer but differs from an accrual-basis P&L that
  would recognize it in June; this report does not attempt accrual
  recognition.
- **Parts cost** is `purchase_order_line_items.quantity_received *
  unit_cost` summed for POs whose `received_at` falls in the period — a
  reasonable proxy for cost of goods sold given no full GL exists, but note
  it's tied to when stock was *received*, not when the vendor invoice was
  *paid* (the schema has no vendor-payment-date field at all; see the cash
  flow section below for why this matters more there).
- **Labor cost, and the unavailable-not-zero rule.** For each closed
  `job_time_entries` row (`clocked_out_at IS NOT NULL`) whose
  `clocked_in_at` falls in the period, duration × the technician's
  `users.hourly_rate` is added to that month's labor cost. Open entries
  (still clocked in, `clocked_out_at IS NULL`) are excluded — there's no
  final duration to compute yet. **If any technician with time entries in a
  month has no `hourly_rate` set, that month's `labor_cost_unavailable` flag
  is `true` and `unrated_technicians` lists them by name (falling back to
  their id if `full_name` is unset) — the reported `labor_cost` figure is
  then a known undercount, never silently presented as a complete number
  with their hours counted as $0.** Both the API response and the frontend
  P&L page surface this as a visible warning banner, not a footnote.
- **Net** = revenue − parts cost − labor cost.

**Cash flow methodology, and the "cost incurred" vs. "cash paid" caveat.**
`GET /reports/cash-flow?start_date=&end_date=` reports cash in (the same
succeeded-`payments` figure as P&L revenue) against **cost incurred** (the
same PO-received-line-items figure as P&L parts cost) — deliberately
labeled `cost_incurred`, not `cash_out`, because **the schema has no vendor
cash-payment-date field anywhere** — `purchase_orders` tracks `received_at`
(when stock arrived) but not when the shop actually paid that vendor's
invoice. Presenting "PO received" as if it were "cash paid to vendor" would
misrepresent accrual timing as cash timing, so the API response includes an
explicit `cost_incurred_caveat` string saying so in plain language, and the
frontend renders it directly under the cash-flow totals rather than only in
docs a user is unlikely to read. `net_cash` = cash in − refunds out − cost
incurred, with the same caveat applying to that figure.

**CSV exports and the QuickBooks Online-compatible transactions bridge.**
Every report now has a CSV export using the same `require_operations` gate
as its JSON counterpart:

- `GET /reports/ar-aging/export.csv` — extends the Phase 8 AR aging report
  (which had no export before this phase).
- `GET /reports/pnl/export.csv`, `GET /reports/cash-flow/export.csv` — one
  row per month plus a `TOTAL` row, mirroring the JSON shape.
- `GET /reports/transactions/export.csv` — a **3-column journal** (`Date`,
  `Description`, `Amount`) covering invoiced revenue collected and PO costs
  incurred for the period, using the widely-documented standard 3-column
  layout for spreadsheet/QuickBooks Online-style CSV import (positive
  amounts for revenue, negative for costs). **This is a CSV export bridge,
  not a live API integration** — confirm the exact column requirements
  against QuickBooks Online's own current import tool before relying on it
  for a real books close, since Intuit has changed its import UI/requirements
  over time and this was not verified against a live QBO account during this
  phase's work.

**Future: live QuickBooks/Xero sync.** A real OAuth-based sync (auto-push
invoices/payments/POs into QuickBooks Online or Xero's ledger, not just a
CSV a bookkeeper imports by hand) would require, at minimum:

1. Registering a developer app with [Intuit
   Developer](https://developer.intuit.com/) (for QuickBooks Online) and/or
   [Xero Developer](https://developer.xero.com/) under **the user's own
   account** — this cannot be done on the user's behalf from inside this
   codebase, and both platforms require an app-review/approval process
   before production API scopes are granted.
2. Implementing the OAuth2 authorization-code flow for each platform
   (QuickBooks uses Intuit's OAuth2 + a company-specific `realmId`; Xero
   uses its own OAuth2 + tenant id), token storage, and refresh-token
   rotation — a materially larger surface than the API-key-free CSV bridge
   shipped this phase.
3. Mapping HarborIQ's simplified P&L (revenue / parts cost / labor cost /
   net) onto a real chart of accounts (e.g. a specific Income account for
   service revenue, a COGS account for parts, an Expense account for labor)
   — a business decision each shop's bookkeeper should make, not something
   this platform should silently default.
4. Ongoing reconciliation handling (partial syncs, sync failures, duplicate
   prevention) that a one-shot CSV export doesn't need to worry about.

This is intentionally **out of scope** for this phase per the phase spec —
no Intuit/Xero developer app is registered for this product, and building a
half-working OAuth flow without one would be worse than a clearly-labeled
CSV bridge that works today.

**Frontend — a new `/reports` section, plus an export button on AR aging.**
`ReportsPage.tsx` adds a P&L tab (a `recharts` bar chart of monthly net
revenue/parts cost/labor cost, plus the full monthly table, plus a
totals-row summary, plus the unrated-technicians warning banner described
above when applicable) and a Cash Flow tab (a `recharts` line chart of cash
in/cost incurred/net cash, the monthly table, and the `cost_incurred_caveat`
rendered verbatim), each with its own date-range picker and an "Export CSV"
button, plus a page-level "Export QuickBooks CSV" button for the
transactions journal. `ArAgingPage.tsx` gained an "Export CSV" button using
the same download helper. No chart library existed in `package.json` before
this phase (checked first, per the phase spec) — `recharts` was added as a
lightweight, actively-maintained option (v3). CSV downloads use a new
`downloadFile` helper in `lib/api.ts`: the existing `apiRequest`/`rawRequest`
functions only ever parse JSON bodies, so a separate raw-`fetch`-plus-blob
helper was needed for `text/csv` responses, reusing the same
401-refresh-and-retry policy as every other authenticated request rather
than duplicating a second, weaker auth path. `/reports` is registered in
`App.tsx` and `AppShell`'s nav following the exact `ArAgingRoute`/`TeamRoute`
pattern: gated behind `canManageOperations(user?.role)`, with a
permission-denied message rather than a 404 for a logged-in user who simply
lacks the role.

### What's intentionally NOT here yet (Phase 14)

- **Live QuickBooks/Xero OAuth sync.** Covered in detail above — this phase
  ships a CSV export bridge, not a connected integration; no Intuit/Xero
  developer app is registered for this product.
- **A full double-entry general ledger.** No chart of accounts, no journal
  entries, no balance sheet — this phase's P&L/cash-flow reports are
  computed directly from operational tables (invoices, payments, refunds,
  POs, time entries), not from ledger postings, matching the roadmap's own
  "pragmatically smarter than building a full GL from scratch" framing.
- **Accrual-basis P&L.** Revenue is recognized on cash collection
  (`payments.created_at`), not on invoice issuance — an invoice sent in one
  month and paid the next shows up as next month's revenue. This is called
  out explicitly in the methodology above and in the API response shape,
  not hidden.
- **Vendor cash-payment tracking.** `purchase_orders` has no
  vendor-payment-date field, so "cost incurred" (PO received) is reported
  instead of "cash paid to vendor," with an explicit caveat string returned
  by the API and rendered in the UI. Adding real accounts-payable tracking
  (when the shop actually pays each vendor bill) would be a larger, separate
  feature.
- ~~**PDF report exports.**~~ **Shipped in Phase 17** —
  `GET /reports/pnl/export.pdf` and `GET /reports/cash-flow/export.pdf`
  (reusing the `invoice_pdf.py` reportlab pattern, see `app/services/report_pdf.py`)
  now sit alongside the CSV exports below.


## Marina/slip management (Phase 15)

Every prior phase targeted the mobile-marine-mechanic wedge — a technician
who drives to a boat. This phase adds the other half of the marine-services
market DockMaster owns: fixed-location marinas and boatyards that rent wet
slips, dry-stack storage, and moorings. It is an explicitly approved
business-model fork, not scope creep — a marina customer is still a
`Customer` (Phase 2) and a boat in a slip is still a `Vessel` (Phase 2),
so nothing here duplicates either table.

**Migrations `0015_marina_slip_management` and
`0016_marina_slip_management` — a two-part split, same reason as migration
`0005`.** This phase adds a new `storage` value to the existing
`job_line_item_kind` enum, then uses that value in a CHECK constraint in the
same phase's work. PostgreSQL allows `ALTER TYPE ... ADD VALUE` inside a
transaction (12+) but forbids *using* that new value — even inside a CHECK
constraint expression — in the same transaction it was added in ("unsafe
use of new value"), the identical restriction migration `0005` documented
for `token_purpose`'s `user_invite` value. `0005` only ever needed the
"add it, don't use it yet" half, so it stayed one file; this phase's CHECK
constraint genuinely needs the new value in the same piece of work, so it is
split across two migrations/transactions instead: `0015` only adds
`job_line_item_kind`'s `storage` value, and `0016` — applied immediately
after, in its own transaction — is where `storage` actually gets referenced,
in `job_line_items`' new `ck_job_line_items_exactly_one_source` constraint
and the new `slips`/`slip_reservations`/`dry_stack_launch_requests` tables.
Verified by dropping and recreating the database and reapplying migrations
`0001`–`0016` from scratch during this phase's work, not just applied
incrementally on top of already-migrated state.

**One `slips` table, not one per space type.** A wet slip and a dry-stack
rack space need the same core fields — identifier, dimensions, status, a
rental rate — and diverge only on a handful of columns (dry stack needs
`rack_level`/`rack_position` for forklift retrieval; a wet slip's `depth_ft`
is meaningless for a rack space stacked in a shed). A `slip_type`
discriminator (`wet_slip` / `dry_stack` / `mooring`) on one table keeps every
query that wants "all rentable spaces" (the slip map, availability search,
storage billing) single and simple instead of forcing a UNION across two
near-identical tables, at the minor cost of `depth_ft`/`rack_level` being
mutually meaningless depending on `slip_type` — enforced by
`ck_slips_depth_only_wet_or_mooring` and `ck_slips_rack_only_dry_stack` CHECK
constraints, not left to convention. `dry_stack_launch_requests` is its own
table (scheduling a forklift pull to launch/retrieve a boat is a distinct
event from the rental itself, and can span, precede, or outlive a given
reservation).

**`SlipReservationSM` — the same `FOR UPDATE`-before-`assert_transition()`
discipline as every other state machine in this codebase.**
`pending → confirmed → checked_in → checked_out`, with `cancelled` reachable
from `pending`, `confirmed`, or `checked_in`. `app/services/slip_reservations.py`
loads the reservation row with `SELECT status ... FOR UPDATE` before handing
the current and target status to `SlipReservationSM.assert_transition()`,
the identical pattern `JobSM`/`PurchaseOrderSM`/`InvoiceSM` already use — no
reservation transition is ever decided from a stale in-memory read.

**Double-booking is prevented at the database level, not just in
application code.** `slip_reservations.create` does check availability
before inserting, but that check-then-insert is not atomic across sessions
— two concurrent callers can both pass the check before either commits. The
real guarantee is `ex_slip_reservations_no_overlap`, a `btree_gist`
`EXCLUDE` constraint on `slip_reservations(slip_id, stay_range)` (migration
`0016`; `stay_range` is a generated `DATERANGE` column derived from
`start_date`/`end_date`). Postgres has no native way to express "no two rows
with the same `slip_id` may have overlapping date ranges" as a CHECK
constraint (CHECK constraints cannot see other rows); an `EXCLUDE`
constraint can, but needs a GiST operator class for every column it
compares, and there is no default GiST opclass for plain equality on a UUID
column — `btree_gist` supplies one, the standard, documented way to combine
"equal on this column" with "overlaps on this range" in a single exclusion
constraint. `docker-entrypoint-initdb.d/00_roles.sql` installs the
extension (superuser-only, same pattern as `pgcrypto`/`citext`) before this
migration runs. This is verified with a genuinely concurrent test —
`tests/test_slip_reservation_overlap.py` fires create attempts from separate
threads and separate database connections/sessions (the same pattern
`test_inventory_concurrency.py` uses for `use_inventory_part_atomic`) at the
exact same slip and overlapping dates, and asserts exactly one attempt wins
while the other gets a clean `Conflict`, never a silent double-booking or an
unhandled database error.

**Storage billing reuses the existing job-invoicing pipeline instead of a
second one.** `job_line_items.job_id` became nullable and a new nullable
`slip_reservation_id` FK was added, with `ck_job_line_items_exactly_one_source`
enforcing that exactly one of `job_id`/`slip_reservation_id` is set per line
item — a storage charge is a line item exactly the way a labor or parts
charge is, just sourced from a reservation instead of a job.
`POST /slip-reservations/{id}/generate-storage-charge` creates a `storage`-
kind line item priced from the slip's `daily_rate`/`monthly_rate` (or an
explicit override), and `POST /slip-reservations/{id}/generate-invoice`
calls a new `create_invoice_from_reservation()` in `app/services/invoices.py`
that reuses the exact same subtotal/tax/total math and line-freezing
behavior `create_invoice()` already established for job-sourced invoices,
rather than a parallel, easy-to-drift-out-of-sync implementation.

**A CSS-grid slip map, not a second Leaflet map.** Phase 11's Leaflet/
OpenStreetMap map answers "where is this technician right now" — a
continuously moving point on a real-world map. A marina's slip map answers a
different question, "which of my fixed, already-known-layout slips are free
right now," which a CSS grid keyed on each slip's `identifier` answers
directly, with color-coded status, without a mapping-library dependency or
requiring real GPS coordinates for every slip. `slips.latitude`/`longitude`
are optional columns kept for a possible future customer-facing "find my
dock" view, but the staff `SlipMapPage` itself neither requires nor renders
them.

**Backend**: `app/api/v1/routes/{slips,slip_reservations}.py`,
`app/schemas/{slips,slip_reservations}.py`,
`app/services/{slips,slip_reservations}.py` — all gated behind
`require_operations`, the same permission tier as inventory, vendors, and
purchase orders.

**Frontend**: three new pages — `SlipsPage` (`/marina/slips`),
`SlipReservationsPage` (`/marina/reservations`), and `SlipMapPage`
(`/marina/slip-map`) — registered in `App.tsx` and `AppShell`'s nav
following the exact `ArAgingRoute`/`TeamRoute`/`PurchaseOrdersRoute` pattern:
gated behind `canManageOperations(user?.role)`, with a permission-denied
message rather than a 404 for a logged-in user who simply lacks the role.
`slipsApi`/`slipReservationsApi` in `lib/services.ts` call
`api.get`/`api.post`/`api.patch`, the same centralized, Bearer-token-
authenticated request helpers every other page uses — no per-page auth
handling was needed here, including no CSRF header on the
reservation-creation mutation: Phase 16's CSRF check is scoped entirely to
`POST /auth/refresh` (the one endpoint that relies on the httpOnly refresh
cookie instead of the `Authorization: Bearer` header), and `SlipMapPage`'s
mutation, like every other authenticated mutation in this app, goes through
`api.post` unchanged.

### What's intentionally NOT here yet (Phase 15)

- **Payment-processing changes beyond line items.** Storage charges flow
  through the existing Stripe Checkout/invoice pipeline unchanged — no new
  payment method or processor integration was added.
- **Crane/forklift IoT integration.** Dry-stack launch/retrieval requests
  are logged and scheduled (`dry_stack_launch_requests`), not dispatched to
  or tracked by any physical equipment. No crane/forklift/boat-lift
  equipment is currently owned or operated, so there is no vendor API to
  build against yet — see `docs/SCALING_AND_EQUIPMENT_INTEGRATION.md`.
- ~~**Recurring/automatic monthly storage billing.**~~ **Shipped in Phase
  17** — a `slip-storage-billing-daily` Celery beat task
  (`generate_recurring_monthly_charges_for_company` in
  `app/services/slip_reservations.py`) now auto-generates each active
  reservation's storage charge on a monthly cadence, idempotently (it will
  not double-charge a reservation that already has a charge for the current
  billing period). `generate-storage-charge`/`generate-invoice` remain
  available as staff-triggered actions too, for one-off/manual cases.

## Phase 17 — Backlog Completion

This phase closes the small but consequential gaps prior phases had left
explicitly documented rather than papered over. The common design rule is
the same one the rest of HarborIQ uses: extend the existing source of truth
and its transaction boundary instead of creating a second billing, reporting,
authentication, portal, or purchasing path that can drift.

**Recurring monthly slip billing is a scheduled, period-scoped extension of
the Phase 15 line-item design, not a loosening of the one-off charge guard.**
`generate_storage_charge()` still refuses a second manual storage charge for
a reservation, which is the safe behavior for a short stay. Long-running
wet-slip/dry-stack rentals instead go through
`generate_recurring_monthly_charge()`: the daily `slip-storage-billing-daily`
Celery Beat sweep considers only `confirmed`/`checked_in` reservations that
overlap the current calendar month and creates a quantity-1 `storage` line
at the slip's `monthly_rate`. The sweep runs daily rather than only on the
first, so a mid-month reservation or a missed run is picked up on the next
run. Its idempotency key is the exact `[period_start, period_end)` marker
embedded in the line description, not `created_at`: insert wall-clock time
would incorrectly treat a late run, replay, or backfill of (say) June as an
August charge. A repeat for the same reservation/period therefore no-ops,
while a new calendar month remains billable. The same Beat configuration also
now drives the Phase 8 dunning sweep, removing the former external-cron
requirement.

**Report PDFs are renderings of the existing reports, never a competing
calculation.** `GET /reports/ar-aging/export.pdf`,
`/reports/pnl/export.pdf`, and `/reports/cash-flow/export.pdf` stay behind
the existing `require_operations` gate. `app/services/report_pdf.py` first
obtains the same dictionary returned by each report's JSON/CSV path, then
only lays it out with ReportLab — the pure-Python renderer already chosen for
invoice PDFs instead of a separate native-dependency stack. That preserves
one source of truth for bucket totals, cash-basis P&L methodology, and the
cash-flow cost-incurred caveat across all three download formats; it also
reuses the invoice PDF's dark-header, alternating-row visual language rather
than introducing a new report design.

**Access-token revocation is now stateful exactly until a token would have
died anyway.** Access JWTs carry a random `jti`; on logout,
`app/services/auth.py` continues to revoke the refresh-token family and also
writes the *calling* access token's JTI to
`app/core/token_denylist.py`'s Redis key with a TTL equal to its remaining
`exp`. `get_current_principal` verifies the JWT's signature/expiry and then
checks that key on every authenticated request, so the logged-out token is
rejected immediately rather than remaining usable for its short natural
lifetime. Redis errors deliberately **fail open** on both the write and
read path, the same availability-over-this-extra-defense-in-depth trade-off
as rate limiting: refresh-token revocation still prevents minting a new
access token, and an outage's exposure is bounded by the configured
access-token TTL rather than remembered forever.

**Company-wide MFA is a policy enforced at the login decision point, not a
flag that merely decorates the UI.** Migration `0017_company_mfa_policy`
adds `companies.mfa_required NOT NULL DEFAULT false`, leaving existing
tenants unchanged until they opt in. Any authenticated user can read
`GET /companies/me/mfa-policy`, while the `PATCH` toggle is restricted to
owner/admin users. Login locks the user row and reads that company policy in
the same decision: an enrolled user still receives the normal short-lived
TOTP/backup-code pre-auth challenge; an unenrolled user at a mandating
company receives `mfa_required` plus `mfa_enrollment_required`, with neither
real session tokens nor a pre-auth token to bypass enrollment. The setting
takes effect on subsequent logins and deliberately does not retroactively
invalidate already-issued sessions, matching the codebase's broader
role/policy-change semantics.

**“Find my dock” exposes a customer's dock, not a customer-accessible marina
map.** `GET /portal/{token}/dock-locations` resolves the durable portal
magic link into its tenant/customer pair, then `list_dock_locations()` still
filters `customer_id` in SQL as a second, narrower isolation boundary within
that tenant. It returns only that customer's `confirmed` or `checked_in`
reservations whose slips actually have latitude and longitude; pending,
checked-out, cancelled, coordinate-less, and every other customer's rows
are intentionally absent. `PortalDockLocation` at `/portal/:token/dock`
reuses the Phase 11 react-leaflet/OpenStreetMap pattern for a read-only
marker and treats an empty response as the honest “no GPS location on file”
state rather than an error.

**Stripe refunds reconcile even when the initiating action happened outside
HarborIQ.** `charge.refunded` is a third, independent money path alongside
the original payment webhook and the synchronous
`POST /invoices/{id}/refund` flow. Because a Checkout Session's metadata is
not reliably copied to its Charge, webhook company resolution can fall back
through the payment intent already recorded on the invoice. For each
succeeded entry in Stripe's full `refunds.data[]` list,
`reconcile_refund_from_webhook()` finds the invoice by payment intent first,
then by charge identifier; an unresolvable non-HarborIQ charge is a safe
no-op. That full-list walk matters because Stripe re-sends the growing list
for successive partial refunds. Migration `0018`'s partial unique index and
`ON CONFLICT (stripe_refund_id) DO NOTHING` make every individual refund
idempotent across repeated events while the existing invoice state machine
records the resulting partial/full refund state.

**Vendor “deactivation by convention” is now a real archive lifecycle.**
Migration `0019_vendor_active_flag` adds `vendors.is_active DEFAULT true`
and an `(company_id, is_active)` index for the active-only hot path.
`POST /vendors/{id}/status` is a dedicated archive/reactivate action rather
than an ordinary free-text PATCH, preserving a clean place for lifecycle
rules or audit behavior later. The default vendor list — including the
reorder-suggestion-to-draft-PO flow — offers only active vendors, and
`_require_active_vendor()` refuses a new draft against an archived one.
Conversely, `GET /vendors/{id}` and `include_inactive=true` can still find
the row, so historical purchase orders keep rendering the vendor they were
actually placed with. There remains no hard-delete endpoint: preserving that
foreign-key-backed purchasing history is the reason archival was chosen.

### What's intentionally NOT here yet (Phase 17)

Nothing in this phase's six-area backlog was cut or deferred. The
phase-specific work above is complete; limits that belong to longer-lived
product decisions — such as full customer accounts, a general ledger,
vendor-payment tracking, live accounting integrations, and crane/forklift
IoT — remain in their own sections and the consolidated list below rather
than being represented as unfinished Phase 17 work.


## Project layout

```
harboriq/
  alembic/sql/0001_initial.sql        # corrected DDL + RLS + roles + outbox
  alembic/sql/0002_auth.sql           # user roles, sessions, reset tokens, companies RLS
  alembic/sql/0003_crm_operations.sql # customers/vessels/jobs/line items, composite FKs, RLS
  alembic/sql/0004_invoicing.sql      # invoice lifecycle columns, composite FKs, updated_at trigger
  alembic/sql/0005_auth_hardening.sql # lockout columns + user_invite token_purpose enum value
  alembic/sql/0006_dispatch_engine.sql # skills/coords/required_skills + dispatch score cache columns
  alembic/sql/0007_stripe_connect.sql  # stripe_connect_account_id, refunds table, last_reminder_sent_at
  alembic/sql/0008_customer_portal.sql # public_tokens 'portal' purpose, messages table + RLS
  alembic/sql/0009_geocoding.sql       # users.address_text/home_latitude/home_longitude
  alembic/versions/0001_initial_schema.py
  alembic/versions/0002_auth.py
  alembic/versions/0003_crm_operations.py
  alembic/versions/0004_invoicing.py
  alembic/versions/0005_auth_hardening.py
  alembic/versions/0006_dispatch_engine.py
  alembic/versions/0007_stripe_connect.py
  alembic/versions/0008_customer_portal.py
  alembic/versions/0009_geocoding.py
  app/
    core/      config, logging (env-aware JSON/console), observability (Sentry),
               security (argon2 + JWT), rate_limit (login/reset limiter),
               token_denylist (Redis JTI access-token revocation)
    db/        base, session, tenant, models
    api/       deps (auth + job authorization), errors (domain -> HTTP status),
               middleware (request-id correlation + Prometheus metrics)
    api/v1/    routes: auth, users, customers, vessels, jobs, invoices, health,
               inventory, public, stripe_webhooks, dispatch, billing, reports,
               portal, messages, geocode_admin, companies, slips,
               slip_reservations, vendors
    services/  auth, users, crud, customers, vessels, jobs, invoices, stripe_billing,
               state_machines, inventory, public_tokens, outbox, outbox_dispatch,
               email, stripe_webhooks, dispatch, billing (Connect + dunning),
               invoice_pdf, invoice_render, reports, report_pdf, portal, messages,
               geocoding, companies, slip_reservations, vendors
    schemas/   pydantic models (incl. invoices.py, invite + TeamMember/UserUpdate
               schemas in auth.py, dispatch.py, billing.py, reports.py, portal.py,
               messages.py, geocoding.py)
    jobs/      dunning_sweep.py — standalone script, also invoked on the
               hourly Celery Beat schedule
               slip_storage_billing_sweep.py — per-company recurring monthly
               storage-charge fan-out, invoked daily by Celery Beat
               geocode_backfill.py — geocode any un-geocoded customer/user address;
               callable via POST /admin/geocode-backfill or `python -m app.jobs.
               geocode_backfill [--force]`
  tests/       Postgres-backed integration tests
  frontend/    Vite + React + TS SPA (see "Frontend" below)
  scripts/backup_db.sh                # pg_dump wrapper for a host cron job
  docs/DEPLOYMENT.md                  # env vars, compose, reverse proxy, runbook
  docker-entrypoint-initdb.d/00_roles.sql
  docker-compose.yml  docker-compose.prod.yml  Dockerfile  alembic.ini  pyproject.toml
  .github/workflows/ci.yml
```

## Frontend

`frontend/` is a Vite + React 18 + TypeScript single-page app that talks to
the API above over plain `fetch`/JSON. No server-side rendering, no Next.js —
this is deliberately a thin client so the FastAPI backend stays the single
source of business logic.

**Stack:** Vite, React 18, TypeScript, React Router v6, Tailwind CSS,
`@tanstack/react-query` for server-state caching. No Redux (react-query's
cache already covers the app's state needs), no CSS-in-JS.

**Run it:**

```bash
cd frontend
cp .env.example .env      # set VITE_API_URL if the API isn't on localhost:8000
npm install
npm run dev                # http://localhost:5173
```

**Env vars** (`frontend/.env.example`):

- `VITE_API_URL` — base URL of the API, no trailing slash, no `/api/v1`
  suffix (default `http://localhost:8000`). Vite inlines this at *build*
  time, so a container built for one environment cannot be pointed at
  another without rebuilding (see `frontend/Dockerfile`'s `ARG VITE_API_URL`).

**Auth model:** the access token lives in memory only (a React context); the
refresh token travels as an **httpOnly cookie** set by the backend (Phase 16 —
see "Enterprise hardening" above), no longer readable by frontend JavaScript
at all, with a paired readable CSRF cookie echoed back as an `X-CSRF-Token`
header on cookie-reliant requests. On any `401`, the API client
(`src/lib/api.ts`) attempts exactly one silent refresh-and-retry before
forcing a logout and redirecting to `/login` — it never loops.

**Screens covered:** login/signup, an authenticated app shell (sidebar +
topbar with role-aware nav), a dashboard of job/invoice status counts,
customers (list/search/create + detail with vessels), jobs (list/filter,
create, detail with line items and status transitions gated by the exact
same `JobSM` transition map the backend enforces), invoices (list/filter,
detail with line items/totals, send with a copyable pay link, void gated by
`InvoiceSM`, and — new in Phase 8 — a Refund action gated by `canRefund()`
with the amount field defaulting to the invoice's remaining `amount_paid`),
a team page (now invite-link based, see below), a billing settings page
(Stripe Connect onboarding/status card + an on-demand dunning-sweep button,
both owner/admin-only), an AR aging report page (bucketed outstanding-balance
table, owner/admin/office), a staff Messages panel (Phase 9,
owner/admin/office — see below), a live dispatch board with a Leaflet/
OpenStreetMap map (Phase 11, `/dispatch`, open to every authenticated role
— not gated like Messages/Team/Billing, since every technician needs to
see and act on their own column), the public, unauthenticated `/pay/:token`
invoice page, the public, unauthenticated `/accept-invite/:token` page, and
the public, magic-link-gated `/portal/:token/*` customer portal (Phase 9,
see below).

**Billing settings + AR aging (Phase 8).** `BillingSettingsPage.tsx`
(`/settings/billing`, gated by `canManageUsers` — owner/admin, mirroring the
backend's `require_admin`) shows the tenant's Stripe Connect status
(`GET /billing/connect/status`) with a "Connect Stripe" button that requests
an onboarding link and redirects the browser to it
(`window.location.href = onboarding_url`), plus a "Run dunning sweep" button
that calls `POST /billing/dunning/run` and reports how many invoices were
reminded. `ArAgingPage.tsx` (`/reports/ar-aging`, gated by
`canManageOperations` — owner/admin/office, mirroring `require_operations`)
renders the 1-30/31-60/61-90/90+ bucket totals as stat cards plus a
per-customer table, with an explicit empty state when nothing is
outstanding. Both routes are added to the sidebar nav in `AppShell.tsx`
behind the same role gates as their routes.

**Refunds (Phase 8), `InvoiceDetailPage.tsx`.** A "Refund" button appears
only when `canRefund(invoice.status)` — mirrored from the backend's
`InvoiceSM` (`partial`/`paid`/`partially_refunded` can all take another
refund up to the remaining balance; `draft`/`sent`/`void`/`refunded` cannot).
Opening the form defaults the amount field to `invoice.amount_paid` so the
common case (refund everything) is a single click past "open form, confirm";
the amount is still editable for partial refunds. On success, a banner
reports the refunded amount and the invoice's new status badge picks up the
two new tones added this phase (`partially_refunded` → amber,
`refunded` → blue) alongside the existing status colors.

**Customer self-service portal (Phase 9), `src/portal/`.** Five routes
under `/portal/:token/*` — `PortalHome` (`/me`), `PortalJobs`,
`PortalInvoices`, `PortalEstimates`, `PortalMessages` — share a
`PortalLayout` shell that is deliberately isolated from `AppShell`: no
staff nav, no `AuthContext`, no bearer token. Every call goes through
`apiRequest(..., { anonymous: true })`, the same pattern
`PublicInvoicePage.tsx` established, with the magic-link token as a path
segment rather than a header. A 404 on any portal fetch renders the same
"this link is invalid or has expired" message across all five pages
(`PORTAL_INVALID_LINK_MESSAGE` in `PortalLayout.tsx`) rather than five
slightly different ones. `PortalInvoices` reuses the existing pay flow
(`portalApi.invoicePayUrl` → redirect to the returned Stripe Checkout URL,
not a new payment UI); `PortalEstimates`'s "Approve" button calls
`portalApi.estimateApproveToken` then POSTs straight to the existing
public approval endpoint — no duplicate approval logic on the frontend
either. `PortalMessages` is a two-pane chat list (customer messages
right-aligned/dark, staff left-aligned/light) with a send box that
invalidates the `react-query` cache on success.

**Staff Messages panel (Phase 9), `src/pages/MessagesPage.tsx`.** Added to
`AppShell`'s nav behind `canManageOperations` (owner/admin/office,
mirroring the backend's `require_operations` on `/messages`), the same
gating pattern as AR aging. Shows the company-wide inbox (`GET /messages`)
with an "Unread only" toggle, an unread `Badge` on customer messages
nobody has opened, a per-row "Mark read"/"Reply" action, and a reply box
that posts to `POST /messages` with the selected `customer_id`.
`CustomerDetailPage.tsx` gained a "Send portal invite" button (gated by
`canWrite`, next to the customer's name) that calls
`customersApi.sendPortalInvite` and reports success/failure inline — the
staff-side entry point into everything above.

**Live dispatch board + map (Phase 11), `src/pages/DispatchBoardPage.tsx`.**
A native HTML5 drag-and-drop board (one column per active technician plus
an "Unassigned" column) that calls the existing `jobsApi.assign` on drop —
the same call `JobDetailPage`'s `DispatchSuggestions` already makes, left
untouched. `src/components/DispatchMap.tsx` renders a `react-leaflet` map
below the board (free OpenStreetMap tiles, no API key) with technician
markers (refetched every 60s) and job/customer markers. `src/hooks/
useLocationPing.ts` polls the browser Geolocation API every 3 minutes for
technician-role users only and POSTs to `usersApi.pingLocation`, driving a
status banner on the page (`idle`/`unsupported`/`requesting-permission`/
`denied`/`active`/`error`) so a technician always knows whether their
location is actually being shared — see "Live dispatch board, map & SMS"
above for the honest best-effort-not-background-tracking framing. Added to
`AppShell`'s nav as "Dispatch board", open to every authenticated role
(unlike Messages/Team/Billing) since a technician needs to see and act on
their own column.

**Invite flow (Phase 5).** The Team page's "Send invite" form calls
`POST /auth/invites` (owner/admin only) instead of asking the admin to pick a
temporary password for the invitee — the response's `accept_url` is shown
inline with a copy-to-clipboard button, mirroring the existing invoice
pay-link pattern in `InvoiceDetailPage.tsx`. `AcceptInvitePage.tsx` is a new
standalone public route (outside `<ProtectedRoute>`/`<AppShell>`, structured
like `PublicInvoicePage.tsx`): it calls `GET /auth/invites/{token}` to show
who/what/where before the invitee commits to anything, then `POST
/auth/invites/{token}/accept` on submit, and logs the new user straight in
via `AuthContext.acceptInvite` (the same `applyAuthResponse` path `login`/
`signup` use) before redirecting to `/`.

**Covered by tests:** the API client's 401-refresh-and-retry logic, the job
status-transition gating logic, the invoice send/void/refund visibility
logic (`src/lib/*.test.ts`, including the Phase 8 `canRefund()` additions),
component-level tests for the invite flow (`src/pages/TeamPage.test.tsx`,
`src/pages/AcceptInvitePage.test.tsx`) covering invite submission +
accept-link display, server-error surfacing (duplicate email, reused/expired
token), the invite preview render, and the login-and-redirect path on
successful acceptance, and, new in Phase 8, component-level tests for the
billing settings page (`src/pages/BillingSettingsPage.test.tsx` — connected
and not-connected Connect states, the onboarding redirect, dunning-sweep
success), the AR aging page (`src/pages/ArAgingPage.test.tsx` — table
rendering and the empty state), the refund flow on the invoice detail page
(`src/pages/InvoiceDetailPage.test.tsx` — button visibility per status, the
amount-defaulting behavior, a full submit-and-success-banner flow), and the
new `billingApi`/`reportsApi`/`invoicesApi.refund` service functions
(`src/lib/services.billing.test.ts`), and, new in Phase 9, component-level
tests for `PortalHome` (`src/portal/PortalHome.test.tsx` — profile/vessel
rendering and the invalid-link 404 state), `PortalMessages`
(`src/portal/PortalMessages.test.tsx` — message list rendering and sending
a new message), and the staff `MessagesPage`
(`src/pages/MessagesPage.test.tsx` — inbox rendering with the unread badge,
the reply flow posting to the right customer, and the empty state), and,
new in Phase 11, component-level tests for the dispatch board
(`src/pages/DispatchBoardPage.test.tsx` — column rendering, the Leaflet map
rendering, and a drag-and-drop interaction triggering the assign call), the
`useLocationPing` hook (`src/hooks/useLocationPing.test.ts` — non-technician
no-op, unsupported-browser handling, a successful ping, and permission
denial), and the new `usersApi.pingLocation`/`technicianLocations` and
`jobsApi.notifyOnMyWay` service functions
(`src/lib/services.dispatchBoard.test.ts`) — see "Frontend tests" below.

**Deferred:**

- **End-to-end browser tests (Playwright).** Only unit/logic-level Vitest +
  React Testing Library tests exist today; nothing drives a real browser
  through the app yet. (Playwright itself could not be installed in this
  sandbox's OS image for the Phase 5 manual smoke test either — verification
  instead used `tsc -b`, `vite build`, `eslint`, the Vitest suite, and
  curl-driven backend end-to-end checks against the dev server; see the
  Phase 5 delivery notes.)
- Optimistic UI updates, offline support, and any kind of design system
  beyond the shared Tailwind components in `src/components/ui.tsx`.
- **Real-time messaging on the frontend.** `PortalMessages` and
  `MessagesPage` both rely on `react-query` refetch/cache invalidation, not
  a live socket — a new message appears on the next fetch, not instantly.

## Frontend tests

```bash
cd frontend
npm run test        # vitest run (one-shot)
npm run test:watch  # vitest (watch mode)
```

The suite started intentionally small and logic-focused rather than broad: it
exists to lock in pieces of frontend behavior that would silently break the
app if regressed — token refresh, job status gating, and invoice void/send
gating — not to chase coverage numbers. Phase 5 added the first
component-level tests (`@testing-library/react` + `@testing-library/user-event`,
already-installed dependencies that were previously unused) for the new
invite flow, since that flow has enough branching (preview loading/404,
submit success/failure, redirect-on-success) that logic-only unit tests would
not have caught the same class of mistake. Full user flows beyond that are
still exercised manually and via the backend-facing smoke test described in
the delivery notes for each phase; full Playwright E2E remains deferred (see
above — also not installable in this sandbox's OS image, an environment
limitation rather than a scope decision). Phase 9 added component-level
tests for the customer portal (`src/portal/PortalHome.test.tsx`,
`src/portal/PortalMessages.test.tsx`) and the staff Messages panel
(`src/pages/MessagesPage.test.tsx`), for the same reason as Phase 5's invite
flow — both have enough branching (valid link vs. 404, empty vs. populated
inbox, send/reply success vs. failure) that logic-only tests would not have
caught the same class of regression. Phase 11 added component-level tests
for the dispatch board (`src/pages/DispatchBoardPage.test.tsx` — column
rendering, the Leaflet map rendering inside a `MemoryRouter`, and a
drag-and-drop interaction that triggers the assign call) and the
`useLocationPing` hook (`src/hooks/useLocationPing.test.ts` —
non-technician no-op, unsupported-browser detection, a successful ping, and
permission denial), for the same branching-coverage reason as every prior
phase's component tests. Phase 12 added the highest-value tests of this
phase — `src/lib/offlineQueue.test.ts` (enqueue/list/remove, in-order
replay, halt-on-first-failure, attempt-count/lastError tracking on
failure, and an explicit idempotent-duplicate-replay test simulating a
response lost after the server already processed the request) — plus
`src/hooks/useFieldJobs.test.ts` (network-success caches to IndexedDB;
network-failure falls back to the cache with `fromCache: true`; no cache
and offline surfaces an error; `refresh()` re-fetches) and
`src/components/SignaturePad.test.tsx` (Save disabled until a stroke is
drawn, Pointer Event-driven drawing enabling Save and exporting a data URL,
Clear, Cancel, and the `saving` disabled state). The IndexedDB-backed tests
use `fake-indexeddb` (added as a devDependency and wired into
`src/test/setup.ts`) since jsdom has no real IndexedDB implementation. Phase
15 added component-level tests for the three new marina pages
(`src/pages/SlipsPage.test.tsx`, `src/pages/SlipReservationsPage.test.tsx`,
`src/pages/SlipMapPage.test.tsx`) covering list/create/update flows,
availability checking before a reservation is submitted, and the
reservation-lifecycle action buttons (confirm/check-in/check-out/cancel) —
using the same `setCsrfCookie`-plus-`setAccessToken` session-hydration setup
Phase 16 introduced for every other authenticated page test, since
`AuthProvider` now gates its `GET /auth/me` hydration call on the readable
CSRF cookie rather than a frontend-visible refresh token.

## Deployment & observability

Phase 6 added the operational layer this scaffold needed before running
anywhere other than a laptop: structured JSON logging outside development,
request-id correlation end to end, a Prometheus `/metrics` endpoint,
optional graceful Sentry integration, production-hardened multi-stage
Dockerfiles (non-root, healthchecked), a `docker-compose.prod.yml` overlay,
a `pg_dump`-based backup script, and CI hardening (a frontend job, a
Docker-build job, and advisory dependency audits). Full details — the
real environment-variable reference pulled from `Settings`, how to run the
compose overlay, what a reverse proxy in front of this needs to do, and a
first-incident runbook stub — are in **[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**,
not duplicated here.

Stated plainly, because it matters: the **code-level instrumentation hooks**
(JSON logs, request-id correlation, `/metrics`) are real and
test-covered. Standing up the **actual Prometheus/Grafana/Loki stack** that
would scrape/visualize/aggregate them is a deferred infrastructure decision
for whoever hosts this — there is nowhere in this repo to deploy that stack
to. See the consolidated deferred list below.

## What's intentionally NOT here yet

This is the single, deduplicated list of everything still deferred across
every phase so far — sections above go into the *why* for each; this is
just the *what*, consolidated so nothing is scattered or repeated.

**Platform / infrastructure:**
- A real Prometheus/Grafana/Loki (or equivalent) deployment that actually
  scrapes `/metrics` and aggregates logs — the code-level hooks exist (see
  "Deployment & observability" above); the infrastructure to consume them
  does not, and deploying it is out of this repo's scope.
- **S3 lifecycle rules, point-in-time recovery via WAL archiving,
  cross-region replication.** `scripts/backup_db_s3.sh` (Phase 16) pushes a
  correct dump off-host to S3 when configured — see "Enterprise hardening"
  above and `docs/DEPLOYMENT.md`'s "Off-host backups to S3" — but does not
  manage retention/lifecycle policy on the bucket, PITR, or cross-region
  copies; that is bucket/account configuration outside this repo.
- **Actual Cloudflare account/zone provisioning.** Phase 16 documented the
  CDN/WAF configuration an operator should apply (`docs/DEPLOYMENT.md`'s
  "CDN / WAF (Cloudflare)"); nothing was actually provisioned, and there is
  no Terraform/API automation for it here.
- A container registry / tagged-image release process — `docs/DEPLOYMENT.md`'s
  rollback runbook currently assumes redeploying a previous git commit, not
  pulling a previously-pushed image tag.
- **True horizontal auto-scaling / orchestration (Kubernetes, ECS, etc.).**
  Phase 16's multi-instance readiness audit (see "Enterprise hardening"
  above) confirmed running N `app` replicas by hand (e.g. Compose
  `--scale app=N`) behind a load balancer is now safe; there is no
  autoscaler, and Celery workers still run as a fixed pool rather than
  scaling with queue depth.

**Payments:**
- Destination charges / `application_fee_amount` platform-fee revenue on
  top of Stripe Connect — this phase ships **direct charges only** (the
  tenant is the merchant of record on 100% of the connected-account charge);
  HarborIQ's own revenue is SaaS subscription billing only, not a take rate
  on customer payments. Adding a fee later is a parameter change to the
  same Checkout Session call, but is a pricing/legal decision that was
  deliberately not made here — see "Payment architecture" above.
- ~~A scheduled runner (Celery beat/cron) for the dunning sweep~~ **Shipped
  in Phase 17** — see the "Update (Phase 17)" note under "Billing
  operations" above.
- ~~CSV/PDF export of the AR aging report~~ **Shipped in Phase 17** (PDF;
  CSV had already shipped in Phase 14 — see "Billing operations" above).
- The React customer-facing pay page's own dedicated UI polish beyond what
  already exists — covered under "Frontend" below, not repeated here.

**Frontend:**
- End-to-end browser tests (Playwright) — only unit/logic-level Vitest +
  React Testing Library tests exist. Also not installable in this
  sandbox's OS image, an environment limitation rather than a scope
  decision.
- ~~httpOnly-cookie refresh-token storage (currently `localStorage`).~~
  **Shipped in Phase 16** — refresh tokens now use an httpOnly,
  `SameSite=Lax` cookie plus the CSRF control described in "Enterprise
  hardening" above.
- Optimistic UI updates, a design system beyond the shared Tailwind
  components. (Offline support shipped in Phase 12 for the `/field`
  technician view specifically — see below; the main admin `AppShell` is
  still online-only by design, since office staff are not the audience with
  a spotty-connectivity problem.)
- Real-time messaging (`PortalMessages`/`MessagesPage` rely on `react-query`
  refetch, not a socket) — see "Customer portal / messaging" below.

**Customer portal / messaging (see "Customer self-service portal" above
for the full rationale):**
- **Option B — a full customer password/account system.** Option A (a
  durable 90-day magic link extending `public_tokens`) was chosen instead
  for this phase; a real login/password system for customers, with its own
  session management, is deferred until a shared link genuinely proves
  insufficient (e.g. customers needing independent concurrent sessions of
  their own).
- **Real-time messaging (WebSockets/SSE/push notifications).** Both the
  customer portal and the staff Messages panel poll/refetch via
  `react-query`; a new message appears on the next fetch, not instantly.
  The outbox email is the only "push" that exists today.
- **A Celery/cron-scheduled worker for portal-invite and message emails.**
  Same precedent as every other outbox consumer in this repo (see "Redis
  and Celery" above) — dispatch runs via `BackgroundTasks` right after
  commit, not a scheduled worker.
- **Read receipts beyond staff-side "mark read."** The customer portal does
  not mark staff replies read on the customer's behalf, and there is no
  per-message read receipt visible back to the customer.

**Live dispatch board, map & SMS (see "Live dispatch board, map & SMS
(Phase 11)" above for the full rationale):**
- **True background/mobile location tracking.** Pings only happen while a
  technician has the staff web app open in a foreground browser tab with
  location permission granted; closing the tab/browser stops them
  immediately. Deferred to Phase 12, the offline-capable mobile field app.
- **Per-tenant Twilio number routing for inbound SMS.** Inbound messages are
  matched to a customer globally by phone number across all tenants, not by
  which Twilio number received the text — the honest scope for a single,
  currently-unconfigured Twilio number in this workspace. Revisit once more
  than one tenant needs its own dedicated number.
- **Outbound MMS / rich media**, and a **calendar/time-grid view** on the
  dispatch board (this phase ships the column-per-technician kanban board,
  not a time-axis/Gantt layout).
- **Real-time board/map updates (WebSockets/SSE).** The board and map
  refetch on an interval and on manual actions via `react-query`, the same
  trade-off already made for the customer portal's messaging.

**Offline-first mobile field app (see "Offline-first mobile field app
(Phase 12)" above for the full rationale):**
- **A true native App Store/Play Store app.** Requires the operator's own
  Apple Developer/Google Play accounts; the installable PWA is the full
  extent of this phase's "mobile app."
- **True background/mobile location tracking from the field app.** The PWA
  shell now exists to eventually host it, but `useLocationPing` was not
  wired into `/field` this phase — foreground-tab-only location ping from
  Phase 11 is still the only location signal.
- **Push notifications**, requiring a VAPID keypair and backend
  subscription/send path — not implemented.
- **Video/voice-note attachments** — only photo and canvas-signature
  attachments were in this phase's actual scope.
- **Live-ticking "still clocked in" duration** in the admin `JobDetailPage`
  view — computed once at render/mount, not on a ticking interval.
- **Offline conflict resolution beyond append-only actions** — acceptable
  today since clock events/attachments never conflict with each other, but
  would need real design work for any future offline-editable mutable
  field.

**Auth:**
- ~~No MFA yet~~ **Shipped in Phase 16** (self-service TOTP enrollment) and
  **Phase 17** (admin-forced company-wide policy — see [Phase 17 — Backlog
  Completion](#phase-17--backlog-completion)).
- ~~A revoked session's access token stays valid until it expires... Stateful
  access-token revocation remains out of scope~~ **Shipped in Phase 17**:
  a Redis-backed JTI denylist now rejects a revoked access token
  immediately, not just after natural expiry — see [Phase 17 — Backlog
  Completion](#phase-17--backlog-completion).

**AI dispatch engine (see "AI dispatch engine" above for the full
rationale):**
- A normalized skills/proficiency table instead of `TEXT[]` columns on
  `users`/`jobs` — fine for an exact-match Jaccard overlap today, but a real
  taxonomy (with proficiency levels, certifications, synonyms) would need a
  proper join table.
- ~~Real inventory-to-line-item parts-reservation linkage — the parts
  availability factor is a permanent, documented no-op~~ **Shipped in Phase
  13** — see "Inventory, parts & vendors (Phase 13)" above: `job_line_items`
  of kind `part` are now compared against real `quantity_on_hand`, and the
  scoring factor is a live signal, not a placeholder.
- The eventual ML dispatch model itself, once the platform has accumulated
  roughly 500+ real, labeled repair outcomes to train on — see "AI dispatch
  engine" above. Explicitly not attempted now; faking one against no data
  would be worse than the honest rule-based scorer this phase shipped.
- Geocoding integration for customer and technician addresses shipped in
  Phase 10 (see "Team, skills & geocoding" above) — **company** address
  geocoding remains deferred (no address field/route exists for `Company`
  yet); see that section's own "Deferred, on purpose" list.

**Product surface (per the MVP reset in the build spec):** white-labeling /
custom domains, a trained ML dispatch model (see above — the rule-based
engine is real and shipped; the model is not), and the marketplace. Build
the 5-shop pilot first.

Historical note on gaps *fixed* in earlier phases (kept briefly for
context, not because they're still open): Phase 5 added login rate
limiting + account lockout ("Auth hardening" above), rewrote outbox email
dispatch to actually send via SMTP/console fallback, and replaced
admin-set-password user provisioning with invite links. Phase 6 added
everything under "Deployment & observability" above. Phase 7 fixed the
`HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning (renamed to
`HTTP_422_UNPROCESSABLE_CONTENT`) and the `httpx`/TestClient deprecation
warning (pinned `httpx2`), and added everything under "AI dispatch engine"
above. Phase 8 added everything under "Billing operations"
above — Stripe Connect onboarding, refunds, PDF/email invoice delivery,
dunning, and AR aging — plus the corresponding frontend (Refund action,
billing settings page, AR aging page). Phase 9 (this one) added everything
under "Customer self-service portal" above — the magic-link customer
portal (profile, jobs, invoices, estimates, all reusing the existing
pay/approve flows) and customer<->staff messaging — plus the corresponding
frontend (`src/portal/*` pages and the staff Messages panel). None of that
is listed as deferred anymore — see each section's own text for exactly
what changed and why, and "Customer portal / messaging" above for what is
still deliberately deferred within this phase's scope. Phase 10 added
everything under "Team, skills & geocoding" above — self-service +
admin profile editing (`PATCH /users/{id}`, `GET /users`), a real
OpenStreetMap Nominatim geocoding integration wired into user home
addresses and customer addresses with a documented Google Maps/Mapbox
swap point, a backfill job/route for pre-existing un-geocoded seed data,
and the frontend team roster page — plus removed the "real 'list
teammates' screen"/"no user-management endpoints"/"geocoding integration"
items that used to be listed as deferred above. Company address
geocoding remains deferred within Phase 10's own scope — see that
section's text.
