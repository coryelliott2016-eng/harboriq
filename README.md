# HarborIQ v2 — Working Repo Scaffold

Marine service operating system. Corrected implementation of the HarborIQ
build plan: every issue from the technical critique is fixed at the code level.

> **Status:** scaffold, real authentication, the CRM/operations core
> (customers, vessels, work orders), and **invoicing + Stripe payment
> collection** are real and runnable. Models, migrations, services, routes,
> and tests for the **critical fixes**, for **auth + tenant onboarding**, for
> **customers/vessels/jobs**, and for **invoices/payments** all exist and pass.
> The complete React UI, Stripe Connect onboarding, and the AI layer are
> intentionally out of scope — see `../HarborIQ_v2_Corrected_Build_Spec.md`
> for the roadmap.

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
```

## API surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/healthz` | none | liveness |
| GET | `/api/v1/readyz` | none | readiness (DB check) |
| POST | `/api/v1/auth/signup` | none | create a company (tenant) + its first owner, and log in |
| POST | `/api/v1/auth/login` | none | exchange email/password for an access + refresh token pair |
| POST | `/api/v1/auth/refresh` | refresh token | rotate the pair; the presented token is invalidated |
| POST | `/api/v1/auth/logout` | bearer | revoke this device's session (or every device's) |
| GET | `/api/v1/auth/me` | bearer | the authenticated user |
| POST | `/api/v1/auth/users` | bearer, owner/admin | provision a user inside the caller's company |
| POST | `/api/v1/auth/password-reset/request` | none | queue a reset email (always 202) |
| POST | `/api/v1/auth/password-reset/confirm` | reset token | set a new password and revoke every session |
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
| POST | `/api/v1/jobs/{id}/status` | bearer, office or the assigned tech | move through `JobSM`; 409 on an illegal transition |
| POST | `/api/v1/jobs/{id}/line-items` | bearer, office or the assigned tech | record labor, a part or a fee |
| GET | `/api/v1/jobs/{id}/line-items` | bearer | the job's billable lines |
| PATCH | `/api/v1/jobs/{id}/line-items/{line_id}` | bearer, office or the assigned tech | correct a line; 409 once invoiced |
| DELETE | `/api/v1/jobs/{id}/line-items/{line_id}` | bearer, office or the assigned tech | remove a line; 409 once invoiced |
| POST | `/api/v1/inventory/use` | bearer | atomic stock deduction; with `job_id`, bills the part to that work order |
| POST | `/api/v1/invoices` | bearer, owner/admin/office | invoice every currently-uninvoiced line on a job |
| GET | `/api/v1/invoices` | bearer, owner/admin/office | list invoices; filter by status, customer, job |
| GET | `/api/v1/invoices/{id}` | bearer, owner/admin/office | one invoice with its frozen line items |
| POST | `/api/v1/invoices/{id}/send` | bearer, owner/admin/office | draft -> sent; mints a Stripe Checkout Session (best-effort) and a public pay token |
| POST | `/api/v1/invoices/{id}/void` | bearer, owner/admin/office | draft/sent -> void; 409 if any payment has already landed; frees line items for re-invoicing |
| GET | `/api/v1/public/invoice/{token}` | public token | read-only pay page: invoice, line items, live checkout URL |
| POST | `/api/v1/public/estimate/{token}/approve` | public token | public estimate approval (e-sign) |
| POST | `/api/v1/webhooks/stripe` | Stripe signature | idempotent Stripe webhook (subscription billing *and* invoice payment) |

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

**Deferred, on purpose:**
- Stripe Connect (per-tenant merchant-of-record) onboarding — still the single
  platform Stripe account; see "Payment architecture" below.
- Refunds and partial refunds (`refunded`/`partially_refunded` are modeled in
  `invoice_status`/`payment_status` but nothing writes them yet).
- PDF invoice generation and email delivery of the pay link — the outbox
  already queues an `invoice.send` event; nothing consumes it into an actual
  email yet, matching the pre-existing password-reset email gap.
- Automated overdue/dunning reminders against `due_date`.
- The React customer-facing pay page — the API is ready, there's no frontend
  yet in this repo.

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

**Stripe Connect is still the recommended end state** for (2): each tenant
connects their own Stripe account so shop revenue settles directly to the
shop and HarborIQ takes a platform fee, rather than HarborIQ being the
merchant of record for every marine shop's customer payments. This phase
deliberately ships on the single platform Stripe account instead, because
Connect onboarding (Standard vs. Express vs. Custom, KYC, payout scheduling)
is a substantial project of its own and gates on legal/payment-provider
review — building the invoicing lifecycle, webhook disambiguation, and
tenant-safe data model first means the Connect migration later is "point
`stripe_billing.create_checkout_session` at the tenant's connected account,"
not a rewrite. **The final merchant-of-record model still requires
legal/payment-provider review** — do not treat this scaffold as legal advice.
See the corrected build spec, §8.

## Project layout

```
harboriq/
  alembic/sql/0001_initial.sql        # corrected DDL + RLS + roles + outbox
  alembic/sql/0002_auth.sql           # user roles, sessions, reset tokens, companies RLS
  alembic/sql/0003_crm_operations.sql # customers/vessels/jobs/line items, composite FKs, RLS
  alembic/sql/0004_invoicing.sql      # invoice lifecycle columns, composite FKs, updated_at trigger
  alembic/versions/0001_initial_schema.py
  alembic/versions/0002_auth.py
  alembic/versions/0003_crm_operations.py
  alembic/versions/0004_invoicing.py
  app/
    core/      config, logging, security (argon2 + JWT)
    db/        base, session, tenant, models
    api/       deps (auth + job authorization), errors (domain -> HTTP status)
    api/v1/    routes: auth, customers, vessels, jobs, invoices, health, inventory,
               public, stripe_webhooks
    services/  auth, crud, customers, vessels, jobs, invoices, stripe_billing,
               state_machines, inventory, public_tokens, outbox, stripe_webhooks
    schemas/   pydantic models (incl. invoices.py)
  tests/       Postgres-backed integration tests
  docker-entrypoint-initdb.d/00_roles.sql
  docker-compose.yml  Dockerfile  alembic.ini  pyproject.toml
  .github/workflows/ci.yml
```

## What's intentionally NOT here yet

Per the MVP reset in the build spec: the React frontend, white-labeling/custom
domains, the AI engine, the marketplace, and the full observability stack.
Build the 5-shop pilot first. Invoicing-specific deferrals (Stripe Connect,
refunds, PDF/email delivery, dunning) are listed at the end of
"Invoicing & payments" above.

Known gaps in the auth layer specifically:

- No login rate limiting or account lockout — add before public exposure.
- No email transport: `dispatch_pending` in `services/outbox.py` is still a
  skeleton, so password-reset tokens sit in `outbox_events`.
- No MFA yet, though `users.mfa_secret_enc` is reserved for it.
- Provisioning a user requires the admin to choose an initial password; there
  is no invite-link flow.
- A revoked session's access token stays valid until it expires
  (`ACCESS_TOKEN_TTL_MINUTES`, default 15).
