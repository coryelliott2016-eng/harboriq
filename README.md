# HarborIQ — Marine Industry Intelligence & Operations

[![CI](https://github.com/coryelliott2016-eng/harboriq/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/coryelliott2016-eng/harboriq/actions/workflows/ci.yml)

HarborIQ is a multi-tenant operating system for marine-service businesses:
mobile technicians, service companies, boatyards, marinas and multi-location
operators. One system covers the customer and vessel record, service requests
and work orders, estimates and invoices, Stripe payment collection, technician
dispatch, parts and vendors, slips and moorings, reporting, and a customer
portal — with tenant isolation enforced in PostgreSQL, not just in application
code.

> **Release v0.2.1 (2026-10-18).** Start here:
> [Release register](docs/RELEASE_REGISTER.md) (what is done, with evidence) ·
> [Known limitations](docs/KNOWN_LIMITATIONS.md) ·
> [Roadmap, Phases 19–36](docs/ROADMAP_PHASES_19-36.md) ·
> [Changelog](CHANGELOG.md) · [v0.2.1 release report](docs/RELEASE_REPORT_v0.2.1.md) ·
> [Product overview](docs/PRODUCT_OVERVIEW.md) ·
> [Architecture](docs/ARCHITECTURE.md) and [ADRs](docs/adr/) ·
> [API reference](docs/API_REFERENCE.md) ([OpenAPI](docs/api/openapi.json)) ·
> [Database schema](docs/DATABASE_SCHEMA.md) ·
> [Security overview](docs/SECURITY_OVERVIEW.md) ·
> [Deployment](docs/DEPLOYMENT.md) ([Render blueprint](docs/DEPLOYMENT_RENDER.md)) ·
> [Operations runbook](docs/OPERATIONS_RUNBOOK.md) ·
> [Incident response](docs/INCIDENT_RESPONSE.md) · [Testing & QA](docs/TESTING_QA_PLAN.md) ·
> [Customer onboarding](docs/CUSTOMER_ONBOARDING_SUPPORT.md) ·
> [Sales one-pager](docs/SALES_ONE_PAGER.md) · [Marketing site review](docs/MARKETING_SITE_REVIEW.md) ·
> [Historical build log](docs/BUILD_LOG.md)

## Marine ecosystem discovery and controlled rollout

**One Marine Industry. One Intelligent Platform.**

This repository now contains a public industry-discovery experience alongside
the existing service and marina application. This is an incremental foundation,
not a claim that every specialist SaaS module is complete or deployed.

### Verified baseline and implemented scope

The pre-expansion repository contained authenticated customer/vessel records,
repair orders, estimates, invoicing, technician coordination, inventory,
marina slips/reservations, and platform-level public marketing leads.
Dispatch scoring is rule-based. No public LLM gateway, industry selector, or
sector-specific public pages existed in this repository. The separately hosted
marketing site's source and deployment are outside this change; historical
website observations above are not a fresh verification of the live domain.

Anonymous visitors to `/` now see industry discovery; signed-in visitors keep
their existing dashboard. `/discover` is public regardless of login state.
Dedicated public routes use a shared sector catalog:

- `/industries/marinas`
- `/industries/marine-towing`
- `/industries/commercial-fishing`
- `/industries/recreational-fishing`
- `/industries/marine-service`
- `/industries/charters` (including fishing charter businesses)
- `/industries/boat-owners`
- `/industries/dealers`
- `/industries/suppliers`
- `/industries/surveyors`
- `/industries/commercial-fleets`
- `/industries/other` (requirements discovery, not additional launch-day modules)

Selection changes the route, copy, relevant workflows, example AI question,
qualification question, commercial discussion and conversion links. Pages have
individual titles/descriptions, labeled forms, keyboard-accessible controls,
responsive layouts and skip navigation. BrowserRouter path routes are the
default; existing hash-router builds remain supported. Content is client-rendered:
prerendering, sitemap publication and a manual accessibility audit remain
deployment work, not completed SEO/WCAG certifications.

### Shared public intelligence

`POST /api/v1/public/demo` accepts an allowlisted industry and bounded question.
All sectors use the same server-side provider integration and sector policy
loader. The public frontend deliberately omits authentication credentials;
no private tenant records, operational tools, retrieval corpora, fishing
locations, confidential claims or supplier catalogs are connected to the demo.
Questions are sent to the configured external AI provider; the UI warns visitors
not to enter sensitive information. Provider data-processing and retention terms
must be reviewed before enablement. No local prompt/answer storage or raw-prompt
logging is added.

Responses are **unverified, AI-generated informational guidance**, not licensed
technical documentation, professional inspection judgments, compliance
certification, warranties, valuations or executed operations. Emergency guidance
does not dispatch assistance. Public copy states that nothing has been dispatched
and claims no Sea Tow or TowBoatUS affiliation. No real emergency integration
is introduced.

The gateway is disabled by default and returns an honest unavailable response
until explicitly configured; the UI does not substitute canned AI answers.
There are per-client and shared usage budgets, bounded provider calls and
responses, and fail-closed protection for cost-bearing calls when the shared
limiter is unavailable. Existing API status/latency observability remains in use.
This is not yet domain-aware retrieval, model-quality certification, subscriber
entitlements, billable AI metering or a complete commercial intelligence engine.

### Permission-aware acquisition

The existing `POST /api/v1/public/leads` now classifies sector, stated need and
product interest (`operations`, `ai`, or `partnership`). The public form requires
a separate requested email response; email marketing is optional and unchecked.
Marketing permission evidence is stored separately from the requested response.
Legacy requests retain their existing contract with an `other` classification
and no inferred marketing permission.

Leads remain platform records accessible through the existing protected admin
list, not through tenant-facing customer records. Internal notifications include
classification and permissions to support sector-specific internal follow-up.
No automated marketing campaign, cross-company lead distribution, partner
referral, compensation or commercial analytics export is launched. A marketing
checkbox never authorizes partner data sharing. Operational customer records
remain separate; the lead store is not an authorized analytics dataset.

### Controlled deployment gates and deferred scope

1. Apply the new Alembic migration before deploying the lead API; verify service
   role access, protected admin listing and existing tenant isolation in staging.
   Back up first; downgrading removes the new classification/permission fields.
2. Build with `VITE_API_URL` pointing to the actual backend and configure its
   CORS allowlist and ingress request-size/time limits. Use trusted reverse-proxy
   handling for client IPs; do not trust arbitrary forwarded headers. Verify deep
   links using the existing SPA rewrite.
3. Configure Redis and explicitly enable the gateway only after provider
   credentials, model access, data-processing terms, budgets and sector safety
   evaluation are reviewed. Server-only settings are listed in `.env.example`;
   never expose provider keys through `VITE_*`.
4. Verify genuine provider responses and emergency handling in a controlled
   environment, then verify lead persistence, consent evidence and notification
   delivery. Configure email delivery and a monitored internal recipient.
5. Confirm the marketing domain and Privacy/Terms destinations actually serve
   current policies describing the AI provider and permission choices. This
   includes approved lead retention/deletion procedures and permission management
   before any marketing campaign. This change does not attach `harboriq.com` or
   replace another repository's site.
6. Resolve the existing dependency audit gate before production launch, perform
   browser/mobile and accessibility checks, and obtain human deployment approval.

Specialized towing/fishing/charter/fleet/dealer/supplier/survey modules, voluntary
consumer vessel profiles, provider discovery and service quotes remain deferred.
Referrals require purpose-specific authorization, named recipients, access
controls, delivery/status tracking and reviewed commercial agreements.
Aggregated intelligence requires provenance, retention and contractual
restrictions, independently validated data rights, methodology, quality,
effective de-identification and buyer demand. Fishing grounds, live vessel
tracking, confidential pricing, claims and private service records must not
become marketable datasets by default. No prices or revenue forecasts are invented.

### Validation record

The expansion includes regression coverage for every industry page, selector
personalization, anonymous gateway requests, safe text rendering, unavailable/
limited demos, cancellation across sector changes, classified lead requests,
explicit marketing choice and preservation of the authenticated dashboard.
Backend tests exercise provider transport with mocks rather than claiming a
live model deployment.

- Frontend `npm run lint` and `npm run build` passed. The full `npm test` suite
  passed: **35 test files, 164 tests**, including 28 new discovery/routing and
  session regressions. Hash-router CTAs keep the current route and focus their
  target; expired hydration sessions do not force public visitors to log in.
- Backend targeted validation passed **115 tests**, covering sector policy
  loading, every catalog prompt reaching the provider, prompt bounds, emergency
  handling, dispatch/affiliation output rejection, Redis outage and usage limits,
  provider failure, telemetry privacy, classified leads and consent defaults.
  The complete backend `pytest -q` run passed **898 tests, with one skip and no
  failures**; the backup restore rehearsal skip requires `REHEARSAL_ADMIN_URL`.
  Full `ruff check app tests scripts` also passed.
  Migration `0026` was applied to local PostgreSQL; legacy-row upgrade/downgrade
  preservation was tested. API/database references were regenerated with the
  existing generator: **143 operations, 35 tables**, database revision `0026`.
- The existing `npm run audit:ci` gate currently fails on **five pre-existing
  vulnerable packages (two critical, three high)**: `@capacitor/android`,
  `@capacitor/ios`, `brace-expansion`, `source-map-js`, and `undici`.
  No dependency manifests or lockfiles were changed; these are release blockers,
  not newly introduced dependencies or advisories silently allowlisted here.
- Browser smoke tooling was unavailable in this session (Playwright transport
  closed); no browser/mobile or manual accessibility pass is claimed.
- Changed-file secret scanning passed. CodeQL analysis of Python and JavaScript
  found **zero alerts**. The bundled automated code reviewer could not run
  because its configured model was unavailable; this is not a clean-review
  assertion. A separate read-only review of the implementation commit completed
  with **no significant findings**.
- Live provider access, production deployment, real notification delivery,
  referral delivery and paid analytics have not been exercised or launched.

## Status, stated plainly

| Surface | State (2026-10-18) |
|---|---|
| Application code (API + web app + PWA) | Verified in CI on every PR: lint, secret scan, Postgres-backed test suite, frontend type-check/lint/test/build/audit, Docker build. See the [release register](docs/RELEASE_REGISTER.md). |
| Production database | Provisioned on Neon (`harboriq-app-production`), migrated to `0025`, RLS roles in place, no tenants yet. |
| Production API / web app host | **Not yet running.** The Render blueprint (`render.yaml`) is ready; connecting the Render account is a founder action. Until then the product is not reachable by customers. |
| Marketing site | Live at <https://harboriq-gamma.vercel.app> from the separate repo `coryelliott2016-eng/harboriq-marketing-site` ([ADR 0005](docs/adr/0005-marketing-site-separate-deployment.md)). `harboriq.com` is delegated to a Cloudflare account that has not yet been recovered. |
| Certifications | None. HarborIQ is **not** SOC 2, ISO 27001 or PCI DSS certified and does not claim to be. Card data never touches HarborIQ servers (Stripe-hosted elements). |

Anything described in the long-form [build log](docs/BUILD_LOG.md) is a
statement about the code, not about what is deployed.

## Historical build notes

## Stack

- **FastAPI** + **SQLAlchemy 2.0** (sync) + **Pydantic v2**, Python 3.12
- **PostgreSQL 16** with **row-level security** for tenant isolation
  ([ADR 0001](docs/adr/0001-postgres-rls-tenant-isolation.md)); composite
  `(company_id, id)` foreign keys make cross-tenant references unrepresentable
- **Alembic** migrations (SQL-file based, 25 revisions)
- **Redis** for login rate limiting and access-token revocation; **Celery** worker
  + beat for the transactional outbox, dunning and slip-storage billing
  ([ADR 0002](docs/adr/0002-transactional-outbox.md))
- **Stripe** (Checkout, Connect onboarding, refunds, webhooks with idempotency)
- **React 18 + Vite + TypeScript** SPA and offline-capable PWA field app;
  Capacitor shells for iOS/Android (unsigned)
- Structured JSON logging, request-id correlation, Prometheus `/metrics`,
  optional Sentry
- **pytest** integration tests that run against a real Postgres as the
  RLS-constrained app role; GitHub Actions CI; protected `master`
  ([ADR 0006](docs/adr/0006-protected-master-ruleset.md))

## Two database roles

- `harboriq_app` — non-owner; **RLS applies**. Used by the API and the tests.
- `harboriq_service` — **BYPASSRLS**; used only for migrations, webhook tenant
  resolution, public-token global lookup and maintenance. Never serves tenant
  requests.

## Quick start

```bash
cp .env.example .env
docker compose up -d db redis      # Postgres (with role creation) + Redis
pip install -e ".[dev]"
DATABASE_URL=$SERVICE_DATABASE_URL alembic upgrade head   # schema + RLS policies (service role)
pytest -ra                         # Postgres-backed integration tests (app role)
uvicorn app.main:app --reload      # http://localhost:8000/docs

cd frontend && npm ci && npm run dev   # http://localhost:5173
```

`docker compose up` also starts the API, Celery worker, beat and the frontend
if you prefer the full stack in containers. Environment variables are
documented in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md); `.env.example` lists
every setting with a safe default.

## Tests

```bash
pytest -ra                                   # full suite (needs Postgres; see CI for the service config)
pytest -m no_db                              # pure unit tests, no database
cd frontend && npm run lint && npm test && npm run build && npm run audit:ci
```

The CI workflow (`.github/workflows/ci.yml`) runs `secret-scan`, `lint`,
`test`, `frontend` and `docker-build`; all five are required by the
`protect-master` ruleset and must be up to date with `master` before a merge.
See [`docs/TESTING_QA_PLAN.md`](docs/TESTING_QA_PLAN.md) for what each layer
covers and what is deliberately not covered yet (no browser end-to-end suite).

## Project layout

```
alembic/            SQL migrations (alembic/sql) + Alembic revision wrappers
app/
  core/             settings, logging, observability, security, rate limiting, token denylist
  db/               engine/session, tenant context, ORM models
  api/              dependencies, error mapping, middleware, v1 routes (28 routers)
  services/         domain logic (auth, CRM, jobs, estimates, invoices, billing, dispatch, …)
  schemas/          Pydantic request/response models
  jobs/, tasks/     Celery tasks and standalone sweeps (dunning, slip billing, geocode backfill)
frontend/           Vite + React + TypeScript SPA, PWA field app, Capacitor shells
tests/              Postgres-backed integration tests (91 files)
docs/               product, architecture, API, schema, security, operations, release docs
render.yaml         Render blueprint (API, worker, beat, Redis) — see docs/DEPLOYMENT_RENDER.md
docker-compose*.yml, Dockerfile, scripts/   local stack, hardened images, backup scripts
```

## What is intentionally not here yet

The authoritative, deduplicated list lives in
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md). Headline items:
no production host yet, no SMTP relay configured, Stripe live mode never
exercised, labor-tier rate cards not built, no AI diagnostics or
recall/bulletin intelligence (and none is marketed), no browser end-to-end
suite, no third-party penetration test. Crypto-payment and asset-tokenization
code exists behind flags that are **off** pending legal review.

## Contributing / release controls

All changes land through pull requests into `master`; the ruleset blocks
force-pushes and deletions, requires the five CI checks, and requires review
threads to be resolved. Dependabot keeps the frontend and Python dependencies
current; `audit-ci` fails the build on high/critical advisories. Release notes
live in [`CHANGELOG.md`](CHANGELOG.md).

## License

See [`LICENSE`](LICENSE).
