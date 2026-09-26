# HarborIQ Incident Response Plan

Sized for a founder-led team (Cory + first engineer). Complements the
technical first-incident steps in [`DEPLOYMENT.md`](DEPLOYMENT.md#first-incident-runbook-stub).

## Severity

| Sev | Definition | Examples | Response target |
|---|---|---|---|
| SEV1 | Data exposure across tenants, credential/secret compromise, payments wrong, or total outage | Tenant A sees tenant B data; leaked `STRIPE_API_KEY`; invoices charged twice | Start within 30 min, any hour |
| SEV2 | Core workflow broken for all customers, no data exposure | Cannot send invoices; login failing | Start within 4 business hours |
| SEV3 | Degraded or single-customer issue | Email delayed; one report wrong | Next business day |

## Roles

- **Incident lead:** Cory until an on-call rotation exists. Decides severity,
  customer communication, and legal/regulatory notification.
- **Technical lead:** the engineer on duty. Contains, fixes, preserves evidence.

## Steps

1. **Declare.** Open a private GitHub security advisory (SEV1) or a
   private issue; record start time, reporter, and the `X-Request-ID`s involved.
2. **Contain.**
   - Secret leak: rotate immediately (Stripe dashboard → roll key; new
     `JWT_SECRET` forces all users to log in again; rotate DB passwords),
     then redeploy.
   - Tenant exposure: disable the affected route (revert the offending
     release — see OPERATIONS_RUNBOOK rollback) and keep RLS in force;
     never "fix" by switching the app to the service role.
   - Account takeover: revoke the user's sessions (password reset revokes
     refresh tokens) and require MFA re-enrollment.
3. **Preserve evidence.** Export relevant logs (`dc logs app > incident-<date>.log`),
   `audit_log` rows, and Stripe event IDs before cleanup. Do not delete rows.
4. **Eradicate and recover.** Fix via PR (the ruleset applies during
   incidents too; CI must pass). Restore from backup only if data was damaged.
5. **Notify.** For any confirmed exposure of customer personal data, Cory
   decides — with counsel — on notice to affected shops and individuals.
   Florida's Information Protection Act (Fla. Stat. § 501.171) sets notice
   duties and deadlines for breaches of personal information of Florida
   residents; other states' laws may also apply. Confirm obligations with
   counsel; do not rely on this document as legal advice.
6. **Review.** Within 5 business days, write a blameless post-incident
   note: timeline, root cause, what detected it, what changes prevent
   recurrence; add regression tests and update KNOWN_LIMITATIONS.

## Contacts (fill in; keep current)

| Who | Channel |
|---|---|
| Incident lead (Cory) | Phone 941-210-1663 (published on site). Company email currently bounces — see L3 |
| Stripe support | Stripe dashboard → Help |
| Hosting provider | _to be set when L1 is resolved_ |
| Counsel | _to be set by Cory_ |

## Business continuity

- Recovery point objective (target): 24 h (daily backups) until
  point-in-time recovery is available from a managed Postgres provider.
- Recovery time objective (target): 4 h for a single-host rebuild from
  `DEPLOYMENT.md` plus the latest backup.
- These are targets, not measured results; measure them in the first
  restore drill after L1.
