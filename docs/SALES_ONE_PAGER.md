# HarborIQ — One-Page Overview (early access)

**Run your marine-service business from one place: customers and vessels,
work orders, estimates, dispatch, invoicing, and slips — built by a working
marine technician for mobile mechanics, boatyards, and marinas.**

HarborIQ is in early access. We are recruiting pilot shops; there are no
published customer results yet, and we do not claim any.

## Who it is for
- Mobile marine mechanics (1–3 techs) who quote, fix, and bill from the truck.
- Service yards and boatyards coordinating several technicians.
- Marinas that also manage slips, dry-stack, and storage billing.

## What it does today
| Workflow | In the product |
|---|---|
| Customers & vessels | One record per customer with every vessel and its job history |
| Work orders | Status tracking, labor/parts/fee lines, time clock, photos |
| Estimates → approval → invoice | Build an estimate (labor hours, parts, diagnostic fee), email it, customer approves online, convert to an invoice with one click — the invoice matches what was approved |
| Dispatch | Rule-based suggestions that show *why* each tech is ranked (urgency, fit, drive time, parts, workload); you make the call |
| Field app | Works offline on the water and syncs when signal returns |
| Payments | Stripe online payments paid straight to the shop's Stripe account; refunds and payment reminders |
| Customer portal | Owners see their vessels, estimates, invoices, and messages |
| Inventory | Parts, vendors, purchase orders, reorder suggestions |
| Marinas | Slip map, reservations, dry-stack launch requests, recurring storage billing |
| Reports | A/R aging, P&L, cash flow; CSV/PDF export |

## How we protect shop data
Each shop's data is isolated at the database level (PostgreSQL row-level
security), passwords use Argon2id, two-factor authentication is available,
and card numbers never touch HarborIQ (Stripe handles them). HarborIQ does
**not** hold SOC 2, ISO 27001, or PCI DSS certification.

## Early-access pricing (subject to change)
Solo $79/mo · Team $199/mo · Business $399/mo — as published on the pricing
page; pilot operators help set final pricing.

## On the roadmap (not available yet)
Labor rate tiers, AI-assisted diagnostics, recall/service-bulletin lookups,
App Store and Google Play apps.

## Talk to us
Call **941-210-1663** or request a demo at
https://harboriq-gamma.vercel.app/#/demo.
