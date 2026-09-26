# HarborIQ Customer Onboarding & Support Guide

For pilot shops. Describes the product as built in v0.2.0. Items marked
"not yet available" must not be promised to customers.

## Before the shop's first day (HarborIQ staff)

- [ ] Production app URL live and smoke-tested (KNOWN_LIMITATIONS L1).
- [ ] Outbound email working (L5) — otherwise customers never receive
      invoices, estimates, or portal links.
- [ ] Stripe live mode verified (L6) if the shop will collect payments.

## Shop setup (owner, about 30 minutes)

1. **Sign up** at the app's `/signup` page: company name, your name, email,
   password; accept the Terms and Privacy Policy. You become the **owner**.
2. **Turn on two-factor authentication** (Settings → Security, `/settings/security`). Strongly
   recommended for owners and admins.
3. **Invite your team** (Team page, `/team`). Choose a role:
   - *admin* — runs operations and billing settings;
   - *office* — front desk: customers, jobs, estimates, invoices, reports;
   - *technician* — assigned jobs, time clock, photos, parts used.
     Technicians do not see pricing tools, invoices, or reports.
   Invites expire after 7 days.
4. **Connect payouts** (Settings → Billing, `/settings/billing`, Stripe Connect) to receive
   customer card payments directly to the shop's Stripe account.
5. **Add inventory** you want tracked (optional): parts, cost, price,
   reorder point, vendors.

## Daily workflow

1. **Customer & vessel** — create the customer (add an email so they can
   receive estimates and invoices) and their vessel(s).
2. **Job** — open a job for the vessel; schedule it; use **dispatch
   suggestions** (rule-based ranking with an explanation of each factor) to
   pick a technician. You always make the final assignment.
3. **Estimate** — on the job page, *New estimate*: add labor lines (hours ×
   hourly rate), parts, and fees (*Add diagnostic fee* shortcut). Set the tax
   rate that applies to taxable lines. *Create draft estimate*, review, then
   *Send to customer*. The customer gets an email with a portal link.
4. **Customer approval** — the customer opens the portal and approves the
   estimate; HarborIQ records when, from which IP/browser, and which version.
5. **Convert to invoice** — on the job page, *Convert to invoice* on the
   approved estimate. The draft invoice contains exactly the approved lines.
   Add any extra work as separate job line items and invoice it separately.
6. **Invoice & payment** — send the invoice; the customer pays online via
   Stripe. Paid status updates automatically. Void or refund from the
   invoice page if needed.
7. **Reports** — A/R aging, P&L, and cash-flow, with CSV/PDF export.

## Not yet available (do not promise)

Labor rate tiers/rate cards, AI-assisted diagnostics, recall or
service-bulletin lookups, App Store / Google Play apps (the web app works on
phones and can be installed as a PWA), crypto payments.

## Support

- **Hours / channel:** phone 941-210-1663. (Email support will be listed
  once the company mailbox is restored — L3.)
- **When reporting a problem**, include: company name, what you clicked,
  the time, and a screenshot. If you see an error message, include it.
- **Security issues:** report privately via
  [GitHub private vulnerability reporting](https://github.com/coryelliott2016-eng/harboriq/security/advisories/new).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Account locked" at login | 5 failed attempts | Wait 15 minutes or reset password |
| Customer says no estimate/invoice email | Customer has no email on file, or email delivery not configured | Add email; use *Send portal invite* on the customer page |
| "Convert to invoice" not shown | Estimate not yet approved by the customer | Ask customer to approve from the portal |
| Technician can't see pricing | By design (role permissions) | Office/admin handle pricing |
| Online payment button missing | Stripe Connect not finished | Complete Stripe Connect on `/settings/billing` |
