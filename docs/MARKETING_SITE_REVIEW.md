# Marketing Site Review — 2026-09-22

Site: https://harboriq-gamma.vercel.app (Vercel team `harbor-iq`, project
`harboriq`). Source: Perplexity Project files
`website/harboriq-marketing-site/` — **not** in this repository and not
editable from the release session, so the fixes below are queued as exact
copy changes for approval rather than applied.

## What passes

- Every route renders real content: home, features, marinas, pricing,
  security, about, FAQ, release log, privacy, terms, cookies, investors, demo.
- Product screenshots are labeled "Illustrative interface preview with
  sample data, not a live customer deployment"; savings figures are labeled
  "Estimate only — based on illustrative assumptions."
- The security page states plainly that HarborIQ holds no SOC 2, ISO 27001,
  PCI DSS, or HIPAA certification and has not completed a third-party
  penetration test.
- Pricing is labeled early-access and subject to change.
- No testimonials or customer counts are claimed; Terms promise feedback
  will not be published as a testimonial without written permission.
- The demo form fails closed: with no lead database, the site shows
  "Online requests are temporarily unavailable" and a phone CTA instead of
  a fake success.
- `/api/health` returns 200.

## Required corrections (accuracy)

| # | Where | Current | Problem | Replacement copy |
|---|---|---|---|---|
| S1 | Home hero chips, home/features/pricing/about/release-log ("AI dispatch", "AI-assisted dispatch", "AI job scoring", "AI scoring", "PRIORITY SCORE AI") | "AI dispatch" | Dispatch is a deterministic weighted score (`app/services/dispatch.py`; ADR 0003), not AI/ML | "Smart dispatch" / "Rule-based dispatch scoring — see exactly why each tech is suggested" |
| S2 | Features + Marinas slip card ("AI Assignment checks berth dimensions…") | "AI" badge | Slip checks are validation rules | Drop the "AI" badge; keep "Assignment checks berth dimensions, power, and date overlap" |
| S3 | Terms §6 "AI features" | "dispatch scoring, maintenance suggestions, and the website assistant" | No maintenance-suggestion feature exists; dispatch scoring is not AI | "HarborIQ's website assistant uses an AI model. Dispatch suggestions are rule-based. All suggestions can be wrong and require human review." |
| S4 | Privacy "to power in-product AI features" | | No in-product AI features exist | "…to generate replies in the 'Ask HarborIQ' website assistant." |
| S5 | Features dispatch scoring factors ("technician certification") | | Code factors: urgency, revenue, customer value, distance, parts, technician fit, workload | "Scores weigh urgency, technician fit, parts on hand, drive time, and current workload" |
| S6 | About: "ABYC-certified marine technician" | | Needs evidence (certificate number/level) before publishing | Keep only if Cory confirms current ABYC certification; otherwise "experienced marine technician" |
| S7 | Investors page with SAFE terms, cap, and allocation | Public | Publicly advertising offering terms may be general solicitation, which is incompatible with Rule 506(b) and requires 506(c) accredited-investor verification | Counsel decision: remove terms and gate behind a request form, or file/operate under 506(c) |

## Required corrections (function)

| # | Issue | Fix | Owner |
|---|---|---|---|
| F1 | `Cory@HarborIQ.com` in privacy, terms, FAQ, cookies, security: mail bounces (no MX, SPF `-all`) | Restore mailbox (MX/SPF/DKIM) or replace with a working address | Cory |
| F2 | Lead capture 503 | Set `DATABASE_URL` (Postgres) in Vercel project env; redeploy; submit a test lead | Cory |
| F3 | Canonical, OG URL, and sitemap use `https://harboriq.com`, which does not serve this site | Attach domain in Vercel (TXT records in release report) or temporarily point canonical to the live URL | Cory / Eng |
| F4 | Hash routing (`/#/pricing`) limits deep-page SEO | Move to path routes with Vercel rewrites | Eng |
| F5 | Site source outside version control with CI | Move into a repo with lint/link-check/Lighthouse CI | Eng |

## Verification after fixes

- `curl -s https://harboriq.com | grep -i '<link rel="canonical"'`
- Submit a demo request; confirm stored via `GET /api/leads` with `ADMIN_TOKEN`.
- Send a test email to the published contact address.
- Search the built site for `\bAI\b` and confirm every remaining use refers
  to the website assistant only.
