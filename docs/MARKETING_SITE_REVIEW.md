# Marketing Site Review — 2026-09-22

Site: https://harboriq-gamma.vercel.app (Vercel team `harbor-iq`, project
`harboriq`). Source: Perplexity Project files
`website/harboriq-marketing-site/` — **not** in this repository and not
editable from the release session, so the fixes below are queued as exact
copy changes for approval rather than applied.

## In-repository implementation — 2026-10-10 (not deployed)

This session could not resolve either documented marketing hostname. The
external source and its assistant were not inspected or connected; the earlier
observations below are historical, not a fresh production verification.

The repository now has a separate marketing build with public homepage, AI Lab,
contact/early-access form, and technical demo disclosure. The default authenticated
app is preserved. Public route summaries are emitted as HTML, with titles/social
metadata; canonical URLs and sitemap require an owner-verified HTTPS origin.
Previews remain noindex. The existing brand favicon and purple identity are
reused; no testimonials, partnerships, approved prices, or live predictions are
invented.

**AI integration remains blocked:** no verified conversational AI, provider
integration, RAG knowledge store, or predictive model exists in this checkout.
The anonymous API has an expiring, purpose-separated session contract and
fail-closed Redis quotas, but reports unavailable and never fabricates an answer.
Guided categories fill suggested questions; maintenance/service samples are
synthetic, not functioning predictions or generated guidance.

The form reuses the existing FastAPI lead workflow, with inquiry permission,
validation, deduplication, and a bot trap. Storage acknowledgement is distinct
from notification delivery or booking. Aggregate analytics are visit-only
opt-in, accept allowlisted events, and exclude chat/contact payloads; no
advertising integrations or personal attribution were added.

Local verification: frontend lint and both build modes pass; the complete
frontend suite and isolated backend boundary tests were executed. Browser
checks covered public navigation, scenario selection/focus, and layouts at
390, 768, and 1440 pixels, not a WCAG certification or a production E2E run.
Backend tests cover token tamper/expiry, quotas, Redis outage behavior, and
database/tool isolation. All eight existing lead tests ran against a local
PostgreSQL instance and verified persistence/deduplication, not production
storage or SMTP delivery.
The existing `npm run audit:ci` gate fails with **2 critical and 3 high**
dependency findings (Capacitor, brace-expansion, source-map-js, undici). Those
pre-existing dependencies were not changed in this feature branch.

Release prerequisites: obtain the external marketing and AI source plus host
access; validate a real inference path and authorized marine resources; implement
provider token/spend budgets and prompt-injection defenses before enabling live
inference; configure and verify lead database/SMTP; restore domain and legal
pages; approve privacy/retention and pricing; remediate the dependency gate; run
the ten requested acceptance tests in a controlled preview. No production
deployment or live inference/notification success is claimed.

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
