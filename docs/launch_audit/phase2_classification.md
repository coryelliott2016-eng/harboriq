# HarborIQ Launch Audit — Phase 1 Consolidation + Phase 2 P0–P3 Classification

Date: 2026-08-15 (EDT). Evidence basis: repository state at commit `a73d9fe`
(master), CI history on `coryelliott2016-eng/harboriq`, local verified runs.
Full Phase 1 details: `docs/launch_audit/phase1_backend.md`, `docs/launch_audit/phase1_frontend.md`.

Priority definitions (from Phase 1):
- **P0** — critical production/security/data-loss issue or universal launch blocker
- **P1** — blocks a declared release channel or must be closed before that channel launches
- **P2** — non-blocking quality, performance, or test-signal issue
- **P3** — deferred/backlog; explicit business or infra decision required first

## 1. Phase 1 findings — final disposition

| # | Original finding | Priority | Status | Evidence |
|---|---|---|---|---|
| 1 | No clean full-suite backend test result available | P0 | **RESOLVED** | CI `test` job green on every commit through `a73d9fe`; CI run 2026-08-15 log: "763 passed in 537.17s" — 0 skipped, 0 failed (the previous 1 skip is un-skipped, see #6) |
| 2 | pip-audit: 7 known vulnerabilities (pip 25.3 ×5, pypdf 6.14.2 ×2) | P1 | **RESOLVED** | pypdf>=6.15.0 pinned (commit `201169d`); pip-audit re-run 2026-08-15: "No known vulnerabilities found" |
| 3 | Stripe Billing recurring-payment handler was a TODO stub | P1 | **RESOLVED** | Real handler in `app/services/stripe_webhooks.py` (invoice.payment_succeeded / customer.subscription.*); `tests/test_stripe_subscription_billing.py` passing in CI; zero TODO/FIXME markers remain in `app/` |
| 4 | `.env.example` missing 17 Settings values | P2 | **RESOLVED** | Commit `201169d`; REHEARSAL_ADMIN_URL documented as CI-only in `127afc5` |
| 5 | pytest-timeout undeclared | P2 | **RESOLVED** | Declared in `[dev]` extras (commit `201169d`) |
| 6 | Provisioning test skipped when boto3 absent | P2 | **RESOLVED** | boto3>=1.34 declared in `[dev]` (commit `55b36be`); 16/16 provisioning tests pass locally; CI full suite now reports 0 skipped |
| 7 | Mobile store release path incomplete (iOS unsigned, Android signing unverifiable) | P1 (mobile channel only) | **OPEN — human gate** | Requires Apple Developer/App Store Connect + Play Console accounts, signing credentials. Mission rule #9: do not publish mobile until signing/store requirements pass. Not a web-pilot blocker |
| 8 | Frontend main chunk 1,006.65 kB > 500 kB budget | P2 | **RESOLVED** | Route-level code-splitting (commit `53211e3`): main 275.06 kB, ReportsPage 396.52 kB lazy |
| 9 | React Fast Refresh warning `main.tsx:24` | P2 | **RESOLVED** | Commit `53211e3` |
| 10 | No accessibility lint tooling | P2 | **RESOLVED (tooling)** | eslint-plugin-jsx-a11y active in lint gate (commit `53211e3`); full WCAG conformance NOT claimed — manual keyboard/screen-reader/contrast audit remains open as P2 (see §3) |
| 11 | Vitest jsdom "Not implemented: navigation" noise ×3 | P2 | **OPEN** | Cosmetic test-log noise; does not affect results |

Additional items found and fixed after Phase 1 (this session):
- **CI regression** (frontend + docker-build): `--legacy-peer-deps` fallout removed
  `@testing-library/dom` from fresh installs — fixed across ci.yml, mobile.yml,
  `frontend/Dockerfile` (commits `f059bc8`, `13e83c2`, `fed82f9`); CI green.
- **P1 legal gap**: signup had no ToS/Privacy acceptance — required agreement
  checkbox added linking to marketing-site legal pages, with 3 new tests
  (commit `db2be59`); CI green.
- **P2 SAST gap**: `scripts/` (provisioning/ops tooling) had zero lint coverage —
  added to CI lint scope with 2 reviewed S603/S607 suppressions (commit `a73d9fe`).
- **Supply-chain verification**: `httpx2` dev dependency confirmed legitimate —
  Pydantic-stewarded fork of httpx, preferred by Starlette ≥1.2.0 TestClient and
  included in `starlette[full]` (starlette.dev release notes; pypi.org/project/httpx2;
  github.com/pydantic/httpx2). Not a typosquat.

## 2. Pilot capability coverage (14 capabilities, repo evidence)

Capability set enumerated from repository evidence (API routes under
`app/api/v1/routes/`, 84 backend test files, 32 frontend test files, README).

| # | Capability | Backend test evidence | Status |
|---|---|---|---|
| 1 | Auth & multi-tenancy (signup/login/MFA/RBAC/RLS/CSRF/rate-limit) | test_auth_* (9 files), test_rls_* (3), test_mfa, test_jti_denylist, test_company_mfa_policy, test_password_reset | **READY** |
| 2 | CRM: customers & vessels | test_crm_customers, test_crm_vessels, test_crm_rls | **READY** |
| 3 | Jobs / work orders (status machine, line items, time clock, attachments) | test_crm_jobs, test_crm_job_status, test_crm_job_line_items, test_job_time_clock, test_job_attachments, test_state_machines | **READY** |
| 4 | Dispatch & scheduling (rule-based AI scoring, queue, board, candidates) | test_dispatch_scoring, test_dispatch_queue, test_dispatch_candidates, test_dispatch_board_assignment, test_crm_job_dispatch | **READY** |
| 5 | Invoicing (create, lifecycle, PDF/email, public pay links) | test_invoicing_* (3), test_invoice_pdf_email, test_public_invoice_pay, test_public_tokens, test_money_math | **READY** |
| 6 | Stripe billing (subscriptions, Connect, refunds, dunning, webhooks) | test_stripe_* (6 files), test_refunds, test_dunning, test_ar_aging | **READY** (live-mode settlement untested — human gate: real Stripe account keys) |
| 7 | Customer self-service portal + messaging | test_portal_* (6 files) | **READY** |
| 8 | Team management (invites, profiles, roles) | test_auth_invites, test_user_profile, test_auth_rbac | **READY** |
| 9 | Live dispatch board, location ping, two-way SMS | test_location_ping, test_sms_inbound_webhook, test_sms_service | **READY (code)**; SMS needs real Twilio credentials — human gate; email remains primary channel |
| 10 | Offline-first PWA field app | frontend offlineQueue/offlineVault tests, test_offline_queue_age; PWA service worker builds (57 precache entries) | **READY** (no Playwright E2E — sandbox OS limitation, P2) |
| 11 | Inventory, vendors, purchase orders, reorder | test_inventory_* (2), test_vendors, test_purchase_orders, test_reorder_suggestions | **READY** |
| 12 | Accounting & reporting (P&L, cash flow, exports) | test_pnl_report, test_cash_flow_report, test_report_exports, test_report_pdf_exports | **READY** |
| 13 | Marina / slip management (slips, reservations, dry-stack, storage billing) | test_slips, test_slip_* (4 files) | **READY** |
| 14 | Platform hardening (rate limiting, security headers, metrics, backups, Celery, CORS, request-id) | test_rate_limit_redis, test_security_headers, test_metrics, test_backup_restore_rehearsal, test_celery_outbox_tasks, test_cors, test_request_id, test_file_signatures, test_geocoding | **READY** (S3 backup end-to-end against real AWS bucket — human gate) |

Disabled by design (mission rules #7, #8): crypto payments
(test_crypto_payments verifies gating), asset tokenization (test_asset_tokens
verifies gating). Both must remain disabled at launch.

## 3. Remaining open items — classified

### P0 — none known
No open P0 items identified from repository evidence as of `a73d9fe`.

### P1 (channel-specific launch blockers; all are human gates, not code gaps)
| Item | Channel | What's needed (from Cory) |
|---|---|---|
| Mobile store release (iOS signing, Android Play setup) | Mobile apps | Apple Developer Program + App Store Connect; Play Console; 4 Android signing secrets; then signed-device smoke tests |
| Real SMTP credentials (console-log fallback active) | Web pilot (customer-facing email) | SMTP provider account + creds; without it invoice/portal emails are logged, not sent |
| Stripe live-mode keys + end-to-end settlement test | Payments | Live Stripe account; run one real charge/refund cycle |
| harboriq.com domain: ownership/DNS/TLS unverified from repo | Web pilot | Confirm domain control; marketing site deploy; signup ToS/Privacy links point here |
| Production host + database provisioning | Web pilot | Choose host; run docs/DEPLOYMENT.md; provision Postgres with role separation (00_roles.sql) |

### P2 (non-blocking quality)
| Item | Notes |
|---|---|
| Manual accessibility audit (keyboard, screen reader, contrast) | jsx-a11y static lint is active; WCAG conformance not claimed |
| Vitest jsdom navigation warning noise (×3) | Cosmetic |
| No browser-level E2E tests (Playwright) | Not installable in build sandbox; recommend adding in a real CI runner later |
| Geocoding provider outbound rate throttle is per-instance | Only matters if replicas >1; documented in scaling audit |
| `--legacy-peer-deps` tech debt | Remove when eslint-plugin-jsx-a11y ships ESLint 10 peer support |

### P3 (deferred — business/infra decisions, per project backlog)
Prometheus/Grafana/Loki consuming infra; Cloudflare CDN/WAF account provisioning
(tooling + docs shipped, dry-run tested); autoscaling/orchestration; container
registry release process; crane/forklift IoT (no equipment owned); ML dispatch
model (needs ~500+ labeled outcomes); normalized skills taxonomy; white-label,
predictive maintenance, marketplace.

## 4. Phase 2 verdict

- **Web pilot (5-shop)**: no P0s; no code-level P1s remain open. All P1s are
  external human gates (credentials/accounts/domain/host). Code is
  launch-ready pending those gates and Phase 6 staging verification.
- **Mobile channel**: blocked by signing/store human gates (rule #9). Not a
  pilot dependency.
- **Payments**: implementation + webhook coverage complete in test mode;
  live-mode settlement verification is a required pre-revenue human gate.
- HarborIQ remains **pre-revenue**; nothing in this document claims market
  validation (rule #10).
