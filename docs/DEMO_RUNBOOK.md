# HarborIQ Product Demo Runbook

A 30-minute sales walkthrough against seeded staging data for **Gulf Coast
Marine Service**, a fictional Bradenton/Sarasota, FL marine service shop.
Target: complete the full path in ≤ 20 minutes, leaving buffer for questions.

---

## 1. Environments & logins

| Item | Value |
| --- | --- |
| Staging preview | The deployed staging preview (Perplexity app asset "HarborIQ Staging Demo"); serves `frontend/dist` with API proxied to the staging backend on port 8000 |
| Demo company | Gulf Coast Marine Service |
| Owner login | `demo@harboriq.app` |
| Office login | `office@gulfcoastmarine.demo` |
| Tech logins | `tech1@gulfcoastmarine.demo` (Dana Price), `tech2@gulfcoastmarine.demo` (Luis Navarro) |
| Shared password | `HarborDemo!2026` |

All demo accounts share one password. **Never** reuse these credentials or
seed data outside staging — the seeder refuses to run when `APP_ENV`
is not `staging`/`development` unless `--i-know-what-im-doing` is passed.

## 2. Resetting demo data

The seeder is idempotent (deterministic UUIDv5 ids) — safe to run repeatedly.

```bash
# from the repo root, with staging env loaded
set -a; source /path/to/.env.staging; set +a
python scripts/seed_demo.py            # top-up / repair in place
python scripts/seed_demo.py --reset    # wipe tenant + reseed from scratch
```

Run `--reset` **before every demo** so counts and statuses match this script.

> **Footgun:** running `pytest` with the staging `DATABASE_URL` wipes the
> database — test fixtures TRUNCATE all tables between tests. Always reseed
> after running backend tests against the staging DB, or point tests at a
> separate database.

## 3. What the seed contains

4 users, 10 customers, 13 vessels, 16 jobs (7 scheduled / 4 in progress /
5 completed, 3 unassigned for the dispatch demo), 32 job line items,
4 estimates, 8 invoices (2 draft / 3 sent — one overdue / 3 paid),
3 payments, 12 inventory SKUs (2 below reorder point), 2 vendors, 2 POs,
10 slips (wet A/B/C, dry stack DS-*, mooring M-01), 4 slip reservations,
3 customer messages.

AR aging grand total: **$3,588.25**, with Elise Rowan's $722.25 invoice
sitting in the 1–30 day bucket (the "overdue" talking point).

## 4. The 30-minute demo path

1. **Login → Dashboard** (owner login). KPIs are live: jobs by status,
   invoices by status, revenue. Nothing is a mock.
2. **Customers → Cortez Bay Charters.** Customer record with contact info and
   two vessels (Contender 39 ST, Sea Ray SLX 350). Mention "Send portal invite".
3. **Jobs → "Propeller vibration diagnosis."** Work order with labor + parts
   line items, status transitions, dispatch suggestions, field-app activity.
4. **Dispatch board.** 3 unassigned jobs; assign one to Dana or Luis. Live map
   of Bradenton/Sarasota job locations.
5. **Invoices → open a Draft → Send.** A public pay link appears — copy it,
   open in an incognito tab: the customer-facing pay page renders line items
   and totals with **no login**.
   - With Stripe test keys configured, a Checkout button appears — pay with
     test card `4242 4242 4242 4242` (any future expiry / any CVC).
   - Without Stripe keys, the page shows a graceful "online payment is
     temporarily unavailable" note — either state is safe to show.
6. **Field app** (log in as `tech1@...` on a phone or narrow window,
   or use the "Field app" nav entry). Assigned-job list, time clock,
   photos & signatures. The owner account shows an empty field list —
   techs are the field users.
7. **Portal** (optional): "Send portal invite" from a customer page issues a
   tokenized customer-portal link (`#/portal/<token>`).
8. **Slip map** (`Slip map` nav). Occupancy at a glance: wet slips, dry stack,
   mooring, color-coded status.
9. **Reservations → New reservation.** Book slip `DS-2-01` for dates inside
   2026-09-03 → 2026-10-03 and hit Create: **"this slip is already booked for
   an overlapping date range."** The rejection comes from a database
   exclusion constraint, not just UI validation — the anti-double-booking
   guarantee survives concurrent writes.
10. **AR aging** (`AR aging` nav). Buckets with the seeded overdue invoice;
    grand total $3,588.25.

## 5. Talking points / guardrails

- All numbers on screen come from the seeded tenant — **never invent metrics**.
- Crypto payment feature flags are **OFF** for demos.
- Multi-tenant isolation is enforced by PostgreSQL row-level security
  (`FORCE ROW LEVEL SECURITY` + per-request `app.company_id`); even the
  table owner cannot read another tenant's rows.
- Public pay/portal links are scoped, hashed, expiring tokens (72 h TTL) —
  the raw token is shown exactly once.

## 6. Staging deployment notes

- Frontend build for proxied staging hosts (all three flags required):

  ```bash
  cd frontend && VITE_API_URL=__PORT_8000__ \
    VITE_CSRF_COOKIE_NAME=__Host-csrf_token \
    VITE_ROUTER=hash npm run build -- --base ./
  ```

  `VITE_ROUTER=hash` — deep paths under a proxy prefix can't use
  BrowserRouter; `--base ./` — assets must be relative; the `__PORT_8000__`
  sentinel is rewritten to a relative `port/8000` path at upload.

- Backend: uvicorn on port 8000 with `.env.staging` loaded
  (`__Host-` prefixed cookies, `AUTH_COOKIE_PATH=/`).
- Stripe: set `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` (test mode) in
  `.env.staging` to enable the Checkout button on the public pay page.
