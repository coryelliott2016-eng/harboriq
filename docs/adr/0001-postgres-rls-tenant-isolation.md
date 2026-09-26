# ADR 0001 — PostgreSQL FORCE RLS with two database roles

Status: Accepted (records the design in migrations 0001–0025)

## Context
HarborIQ is multi-tenant: many marine-service companies share one database.
A single missed `WHERE company_id = …` in application code would leak one
shop's customers, vessels, or invoices to another.

## Decision
- Every table with `company_id` enables **and forces** row-level security
  with a policy comparing `company_id` to `current_setting('app.current_company_id')`.
- The request path connects as `harboriq_app` (no superuser, no BYPASSRLS)
  and sets the tenant with `SET LOCAL` per transaction (`app/db/tenant.py`).
- A separate `harboriq_service` role (BYPASSRLS) is used only for
  pre-tenant work: webhooks, token resolution, lead capture, migrations,
  backups. Cross-tenant platform tables are revoked from the app role.
- `tests/test_rls_coverage.py` fails CI if a new `company_id` table lacks
  RLS/FORCE/policy or if the app role regains access to service-only tables.

## Consequences
- Isolation is enforced by the database, not by developer discipline.
- Service-role code must set tenant context explicitly; it is kept small and
  covered by tests.
- Connection pooling must not use session-level `SET` (only `SET LOCAL`).
