# seed_demo.py — Spec (from HarborIQ Product Demo Brief, Aug 2026)

Create `scripts/seed_demo.py` that seeds ONE canned demo tenant for founder-led sales demos.

## Tenant
- Company: **Gulf Coast Marine Service** (Sarasota, FL — real-feeling independent marine shop, NOT "Test Co")

## Users (fixed passwords, printed at end of run)
| Role | Login | Purpose |
| --- | --- | --- |
| Owner/admin | demo@harboriq.app | Primary login Cory uses |
| Office | office@gulfcoastmarine.demo | Optional |
| Tech | tech1@gulfcoastmarine.demo | Dispatch/field |
| Tech | tech2@gulfcoastmarine.demo | Dispatch/field |

Passwords: generate ONE fixed strong password shared for demo (e.g. `HarborDemo!2026`), must satisfy app password policy. Print all logins at end.

## Data volumes (minimum viable "full" look)
- Customers: 10 (mix boat owners / 1-2 marina accounts; Sarasota/Bradenton addresses; NO real PII — invented names)
- Vessels: 12-15 (Boston Whaler, Contender, Sea Ray, Grady-White, center consoles; real-feeling names like "Reel Therapy", "Salt Life"; hull/engine/hours/storage fields populated)
- Jobs/work orders: 15-18 — mix of statuses: open, in_progress, completed; 2-3 UNASSIGNED (for dispatch scoring demo); realistic titles (100-hr service, impeller swap, bottom paint, electronics install)
- Job line items: labor + parts on most jobs (oil, impeller, zincs, fuel filters, realistic marine prices)
- Estimates: 3-4 (at least one pending approval)
- Invoices: 8 — draft, sent, paid, ONE overdue (AR aging visual)
- Payments on paid invoices
- Technicians: the 2 tech users w/ skills+addresses if model supports
- Inventory SKUs: 12 (oil, impellers, zincs, filters, belts; 2 low stock below reorder point)
- Vendor: 2 + 1-2 purchase orders
- Slips: 10 (mix wet/dry, varied sizes) — map must look alive
- Slip reservations: 4 (one checked-in; occupancy proves no double-booking)
- Messages: at least 1 customer thread (portal not empty)
- Dashboard KPIs must be non-zero as a result.

## Requirements
- Idempotent AND supports `--reset` (wipe the demo tenant rows and re-seed)
- Guard: refuse to run unless APP_ENV in {development, staging} OR `--i-know-what-im-doing`
- Use SERVICE_DATABASE_URL (service role) or app services layer — whichever matches codebase patterns (look at app/services/, app/db/session.py, tenant RLS in app/db/tenant.py)
- Use the app's real password hashing (look at auth service) so login actually works
- Prints demo URL + logins at the end
- Spread created_at/dates over the last 60 days so reports/AR aging look real; one invoice due date ~3 weeks past
