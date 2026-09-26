# Architecture Decision Records

Short records of decisions that shape HarborIQ. Format: context, decision,
consequences. Status is one of Accepted, Superseded, Proposed.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-postgres-rls-tenant-isolation.md) | PostgreSQL FORCE RLS with two database roles for tenant isolation | Accepted |
| [0002](0002-transactional-outbox.md) | Transactional outbox for email and external side effects | Accepted |
| [0003](0003-rule-based-dispatch.md) | Rule-based, explainable dispatch scoring (not machine learning) | Accepted |
| [0004](0004-estimate-to-invoice-conversion.md) | Estimates convert to invoices by copying and freezing approved lines | Accepted |
| [0005](0005-marketing-site-separate-deployment.md) | Marketing site deployed separately on Vercel; lead capture fails closed | Accepted |
| [0006](0006-protected-master-ruleset.md) | Protected `master` via repository ruleset and required CI checks | Accepted |
