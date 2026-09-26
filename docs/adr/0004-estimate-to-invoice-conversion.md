# ADR 0004 — Estimates convert by copying and freezing approved lines

Status: Accepted (v0.2.0, migration 0024)

## Context
Before v0.2.0 the schema and customer portal supported estimate approval,
but staff had no way to create or send an estimate. The job's line items
are also the draft billing ledger; converting an estimate must not
accidentally bill unrelated job lines.

## Decision
- Staff create estimates (`POST /api/v1/estimates`) with typed lines —
  `labor` (fractional hours × rate), `part`, `fee` (e.g. diagnostic fee) —
  plus a tax rate applied to taxable lines. Totals are computed server-side
  with `Decimal`, half-up to cents.
- Sending (`/send`) moves `draft → sent`, issues a portal token, and queues
  an `estimate.send` outbox email. The status change commits first; if the
  token/email step then fails, the estimate stays `sent` and staff can
  re-share access with "Send portal invite" on the customer page.
- The customer approves via the existing single-use approval link, which
  records IP, user agent and PDF version.
- Converting (`/convert`, only from `approved`) creates a new draft invoice
  with `estimate_id` set and copies **only the estimate's lines** into
  `job_line_items`, frozen to that invoice. Pre-existing uninvoiced job lines
  stay uninvoiced.
- Technicians cannot create, read or convert estimates (pricing is an
  office/admin/owner function).

## Consequences
- The invoice equals what the customer approved.
- Labor rate cards/tiers are not modeled; each labor line carries its own
  rate. A rate-card feature is a future, separate decision.
