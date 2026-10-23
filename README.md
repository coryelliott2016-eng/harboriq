# HarborIQ — Marine Service Operating System

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
