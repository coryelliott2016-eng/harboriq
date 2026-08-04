# HarborIQ — MVP Build Completion Report

**Repository:** [coryelliott2016-eng/harboriq](https://github.com/coryelliott2016-eng/harboriq)
**Branch:** `master` @ [`27b759c`](https://github.com/coryelliott2016-eng/harboriq/commit/27b759ce47427413d736f784588c56b0603dfdde)
**Status:** All 6 planned MVP phases complete. CI green (lint, backend tests, frontend tests, Docker build).
**Test totals:** 283 backend tests passing · 22 frontend tests passing

HarborIQ is a multi-tenant marine-service SaaS platform (FastAPI + PostgreSQL with row-level-security tenant isolation, React/Vite frontend, Stripe billing) built for a 5-shop MVP pilot. This report consolidates the full build history across all six phases.

---

## Phase 1 — Authentication & Multi-Tenancy

Company signup, JWT access/refresh token auth, role-based access control (owner/admin/office/technician), row-level security enforcing tenant isolation at the database layer, and password reset. This established the tenant-safety and state-machine conventions every later phase builds on.

## Phase 2 — CRM & Operations

Customers, vessels, and jobs with line items (labor/parts), a job status state machine with row-level locking to prevent race conditions, and tenant-safe composite foreign keys making cross-tenant data references structurally impossible at the schema level.

## Phase 3 — Invoicing & Stripe Payment Collection

**Commit:** [`361d74a`](https://github.com/coryelliott2016-eng/harboriq/commit/361d74a3ce134f97bd9a95e07bbae9d5ca57658f) · **199 → 241 tests**

- Invoices generated directly from a job's uninvoiced line items, with subtotal/tax/total computed from the database's own generated `line_total` math.
- Full invoice lifecycle (draft → sent → paid/partial/void) enforced by a state machine under row-level locking.
- Stripe Checkout integration with idempotent webhook handling, clearly separated from future SaaS subscription billing so the two payment domains never get conflated.
- A public, token-authenticated pay link customers can use without an account.
- Tenant isolation extended to invoices/payments/estimates with the same composite-FK pattern from Phase 2.
- **Found and fixed along the way:** `invoices.updated_at` had been declared in the ORM since the very first migration but never actually existed in the database.
- **Deferred:** Stripe Connect (per-tenant payouts), refunds, PDF invoice generation + email delivery, automated dunning/overdue reminders, the customer-facing pay page's frontend (API was ready; no UI existed yet).

## Phase 4 — React Frontend

**Commit:** [`e43a49f`](https://github.com/coryelliott2016-eng/harboriq/commit/e43a49faaaa2cebeb060da18636e1d7f6dbb3620) · **+15 frontend tests**

- Vite + React 18 + TypeScript + React Router + Tailwind + react-query SPA, built against the real API (no mocks): login/signup, dashboard, customers & vessels, jobs with inline line-item editing and status-transition gating, invoicing (create/send/void), and the public unauthenticated invoice pay page.
- CORS middleware added to the backend as a prerequisite.
- Verified with a scripted end-to-end smoke test exercising the full signup → customer → vessel → job → line items → status transitions → invoice → send → public pay page flow against the live backend.
- **Backend gaps found and flagged (not silently worked around):** no `GET /auth/users` list endpoint (Team page built invite-only instead of faking a roster); the invoice send response returned a raw internal API path rather than a customer-facing URL (fixed on the frontend by building the link from the token against the SPA's own route).
- **Deferred:** Playwright/E2E browser tests, httpOnly-cookie refresh-token storage (currently `localStorage`, a documented MVP trade-off), a real team-roster screen, optimistic UI/offline support.

## Phase 5 — Production Auth Hardening

**Commit:** [`2c24dfa`](https://github.com/coryelliott2016-eng/harboriq/commit/2c24dfad7d47e182dd04c8d3e08d60898ebe6604) · **244 → 278 backend tests · 15 → 22 frontend tests**

- Per-IP login/password-reset rate limiting (429 + `Retry-After`) and account lockout after 5 failed logins (423, generic message — no user-enumeration side channel).
- Real email transport: SMTP with a console-log fallback for dev, wired into a rewritten outbox dispatcher (claims rows with `FOR UPDATE SKIP LOCKED`, dead-letters after repeated failures), triggered via FastAPI `BackgroundTasks` after each relevant commit.
- Invite-link user provisioning — new teammates set their own password via an emailed link instead of an admin choosing it for them, reusing the existing public-token infrastructure rather than building a parallel system.
- **Critical bug found and fixed:** the original invite-accept logic split a row lock from the update it protected across two separate database sessions — a guaranteed deadlock under concurrency, caught via a hanging test run. Documented as a general rule in the codebase: never split a row lock from the mutation it protects across sessions.
- **Deferred:** MFA/TOTP, stateful access-token revocation (a revoked session's access token remains valid until its 15-minute TTL expires — an accepted, documented trade-off), Redis-backed distributed rate limiting, a Celery/Redis task queue.

## Phase 6 — Deployment & Observability Hardening

**Commit:** [`27b759c`](https://github.com/coryelliott2016-eng/harboriq/commit/27b759ce47427413d736f784588c56b0603dfdde) · **278 → 283 backend tests**

- Structured JSON logging (console-readable in dev) with request-ID correlation across every log line for a request.
- A `/metrics` Prometheus endpoint (request counts and latency histograms).
- Optional Sentry error tracking that no-ops cleanly when unconfigured.
- Production-hardened, non-root, multi-stage Docker images with health checks for both backend and frontend, plus a `docker-compose.prod.yml` overlay (no host-exposed database port, restart policies, resource limits).
- CI hardened with a frontend test job and a Docker build job — the latter is the first real build of either image, since this sandbox has no Docker daemon to test locally; **confirmed green on GitHub Actions** after this phase shipped.
- A database backup script and a full deployment runbook (`docs/DEPLOYMENT.md`).
- **Deferred:** an actual Prometheus/Grafana/Loki deployment (the code-level hooks are real; the infrastructure to consume them is an operator decision), managed off-host backups, a CDN/WAF, Redis/Celery, horizontal scaling, a container registry/release process.

---

## Consolidated Deferred Backlog

| Domain | Deferred items |
|---|---|
| Platform / infra | Prometheus/Grafana/Loki stack, managed off-host backups, CDN/WAF, Redis/Celery, horizontal scaling, image registry/tagged releases |
| Payments | Stripe Connect (per-shop payouts), refunds, PDF invoice generation + email delivery, automated dunning |
| Frontend | Playwright E2E tests, httpOnly-cookie refresh storage, a real team-roster/list-users screen, optimistic UI/offline support, broader design system |
| Auth | MFA/TOTP, stateful access-token revocation |
| Product surface (separate future initiative, not MVP scope) | White-labeling/custom domains, an AI dispatching/predictive-maintenance engine, a marketplace |

## Where Things Stand

A marine shop can sign up, manage customers/vessels/jobs, invoice work and collect payment via Stripe, and run the whole thing in production with real logging, metrics, and error tracking — not just a backend API. The full environment variable reference, deployment steps, and first-incident runbook live in [`docs/DEPLOYMENT.md`](https://github.com/coryelliott2016-eng/harboriq/blob/master/docs/DEPLOYMENT.md); architecture and API details live in the repository [`README.md`](https://github.com/coryelliott2016-eng/harboriq/blob/master/README.md).
