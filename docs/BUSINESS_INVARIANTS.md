# Protected HarborIQ business invariants

These rules are product and safety boundaries, not implementation suggestions.
Changes that would alter them require explicit maintainer approval and updated
acceptance tests. The cited ADRs and tests are the authoritative implementation
references.

## Tenant isolation

- A tenant is identified from verified authentication context, never from an
  untrusted request field.
- Tenant-owned rows are protected by PostgreSQL `ENABLE` and `FORCE ROW LEVEL
  SECURITY` policies. The application role is not a superuser and does not
  bypass RLS; tenant context is transaction-local.
- The service role is reserved for explicitly identified pre-tenant work.
  Application requests must not silently switch to it to get around RLS.
- Cross-tenant reads and mutations must not disclose resource existence; API
  access to another tenant's resource returns not found.

**References:** [ADR 0001](adr/0001-postgres-rls-tenant-isolation.md),
`app/db/tenant.py`, `tests/test_rls_coverage.py`,
`tests/test_rls_isolation.py`, and `tests/test_invoicing_rls.py`.

## Authorization and human control

- Every protected operation enforces the existing role and resource
  authorization rules. A caller's role or tenant must not be inferred from
  client-supplied claims that have not been verified.
- Technicians do not set customer pricing or create, read, or convert staff
  estimates.
- Dispatch ranking remains deterministic and explainable; a human makes the
  final assignment.

**References:** `app/api/deps.py`, `docs/adr/0003-rule-based-dispatch.md`,
`docs/adr/0004-estimate-to-invoice-conversion.md`, and
`tests/test_estimates.py`.

## Pricing and customer approval

- The server calculates line totals, subtotals, tax, and totals using
  `Decimal` and rounds money to cents. Client-supplied calculated totals are
  never authoritative.
- Tax applies only to taxable lines. Tax rate and line values remain within
  their schema bounds.
- An estimate can be converted only after customer approval. Conversion
  copies only the approved estimate lines; unrelated job lines must not enter
  the invoice. The invoice amount must match the approved estimate.
- Do not add an implicit labor rate card or silently reinterpret existing
  per-line pricing; that requires a separate product decision.

**References:** `app/services/estimates.py`, `app/schemas/estimates.py`,
`docs/adr/0004-estimate-to-invoice-conversion.md`,
`tests/test_estimates.py`, and `tests/test_money_math.py`.

## Payments and refunds

- Card data is handled by the payment processor, not stored or received by
  HarborIQ.
- A verified payment event is applied only to the invoice resolved for the
  correct tenant. Event replay must not create another payment or apply the
  amount twice.
- `amount_paid` cannot exceed the invoice total; balances and payment state
  must remain consistent with recorded amounts.
- Refunds cannot exceed the amount collected less prior refunds. Concurrent
  refunds serialize on the invoice; a failed processor refund does not mark the
  invoice refunded.
- Payment/refund authorization, tenant scoping, and webhook signature and
  idempotency checks are not optional.

**References:** `app/services/invoices.py`, `app/services/stripe_webhooks.py`,
`docs/adr/0001-postgres-rls-tenant-isolation.md`,
`tests/test_stripe_invoice_webhook.py`, `tests/test_refunds.py`, and
`tests/test_crypto_payments.py`.

## Lifecycle and side effects

- Business state changes use the existing state machines and legal transitions;
  terminal or otherwise illegal transitions must fail rather than be forced.
- External side effects are queued transactionally through the outbox where
  that pattern is in use. A retry must not duplicate a business effect.
- Physical and financial facts (for example, a received purchase order or a
  checked-in slip reservation) must not be reversed through an ordinary
  lifecycle transition.

**References:** `app/services/state_machines.py`,
`docs/adr/0002-transactional-outbox.md`, and
`tests/test_state_machines.py`.

## Required change discipline

For a change that touches these boundaries:

1. Identify the invariant and its current enforcing code and test.
2. Get maintainer approval before changing the invariant or its enforcement.
3. Add or update an acceptance test that would fail for a plausible unsafe
   implementation.
4. Run the relevant existing tests and CI checks; do not weaken a guardrail to
   make the change pass.
