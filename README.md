# HarborIQ v2 — Working Repo Scaffold

Marine service operating system. Corrected implementation of the HarborIQ
build plan: every issue from the technical critique is fixed at the code level.

> **Status:** scaffold, real authentication, and the CRM/operations core
> (customers, vessels, work orders). Models, migrations, services, routes, and
> tests for the **critical fixes**, for **auth + tenant onboarding**, and for
> **customers/vessels/jobs** are real and runnable. Invoicing and payments are
> the next phase; the complete UI and the AI layer are intentionally out of
> scope — see `../HarborIQ_v2_Corrected_Build_Spec.md` for the roadmap.

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
| POST | `/api/v1/public/estimate/{token}/approve` | public token | public estimate approval (e-sign) |
| POST | `/api/v1/webhooks/stripe` | Stripe signature | idempotent Stripe webhook |

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

## Payment architecture

Stripe Connect is the recommended default: each tenant connects their own
Stripe account; HarborIQ charges a platform fee. **The final merchant-of-record
model depends on the Connect configuration and requires legal/payment-provider
review** — do not treat this scaffold as legal advice. See the corrected build
spec, §8.

## Project layout

```
harboriq/
  alembic/sql/0001_initial.sql        # corrected DDL + RLS + roles + outbox
  alembic/sql/0002_auth.sql           # user roles, sessions, reset tokens, companies RLS
  alembic/sql/0003_crm_operations.sql # customers/vessels/jobs/line items, composite FKs, RLS
  alembic/versions/0001_initial_schema.py
  alembic/versions/0002_auth.py
  alembic/versions/0003_crm_operations.py
  app/
    core/      config, logging, security (argon2 + JWT)
    db/        base, session, tenant, models
    api/       deps (auth + job authorization), errors (domain -> HTTP status)
    api/v1/    routes: auth, customers, vessels, jobs, health, inventory, public,
               stripe_webhooks
    services/  auth, crud, customers, vessels, jobs, state_machines, inventory,
               public_tokens, outbox, stripe_webhooks
    schemas/   pydantic models
  tests/       Postgres-backed integration tests
  docker-entrypoint-initdb.d/00_roles.sql
  docker-compose.yml  Dockerfile  alembic.ini  pyproject.toml
  .github/workflows/ci.yml
```

## What's intentionally NOT here yet

Per the MVP reset in the build spec: the React frontend, white-labeling/custom
domains, the AI engine, the marketplace, and the full observability stack.
Build the 5-shop pilot first.

Known gaps in the auth layer specifically:

- No login rate limiting or account lockout — add before public exposure.
- No email transport: `dispatch_pending` in `services/outbox.py` is still a
  skeleton, so password-reset tokens sit in `outbox_events`.
- No MFA yet, though `users.mfa_secret_enc` is reserved for it.
- Provisioning a user requires the admin to choose an initial password; there
  is no invite-link flow.
- A revoked session's access token stays valid until it expires
  (`ACCESS_TOKEN_TTL_MINUTES`, default 15).
