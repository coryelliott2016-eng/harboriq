# Known Limitations Register — v0.2.0

Every item here is real and current as of 2026-09-22. Severity uses the
release-blocking scale: **Critical/High** would block a paid production
launch; **Medium/Low** are accepted for a supervised pilot.

| # | Limitation | Severity | Impact | Resolution path | Owner |
|---|---|---|---|---|---|
| L1 | No production API/web-app host is running | Critical (for SaaS launch) | Customers cannot use the app; only the marketing site is live | Production Postgres is provisioned (Neon `harboriq-app-production`, migrations at 0025, RLS roles verified 2026-09-22). Remaining: connect Render and apply `render.yaml` (see `docs/DEPLOYMENT_RENDER.md`) | Cory (connect Render) |
| L2 | Primary domain `harboriq.com` is in a Cloudflare account not reachable with current credentials; it does not serve the site | High | Canonical/OG/sitemap URLs and the listed email domain do not work | Log in to the Cloudflare account holding the zone and add the Vercel records (see release report) | Cory |
| L3 | Company email `Cory@HarborIQ.com` bounces (no MX, SPF `-all`) | High | Privacy/terms/security contacts unreachable | Restore mail provider MX/SPF/DKIM or change published address | Cory |
| L4 | ~~Marketing lead capture returns 503~~ **Resolved 2026-09-22** | — | Live `POST /api/leads` returned 201 and stored the row in Neon (`harboriq-marketing`); two labeled synthetic test rows (ids 1-2, `@example.invalid`) remain as evidence | Add lead-notification email once SMTP/email is restored | Cory |
| L5 | No SMTP relay configured | High (for pilot) | Invoice/estimate/portal/password-reset emails are logged, not delivered | Configure `SMTP_*` settings | Cory |
| L6 | Stripe live mode never exercised | High (for payments) | Real settlement/refund untested | Live keys + one real charge/refund cycle | Cory |
| L7 | Labor tiers / rate cards not built | Medium | Rates typed per labor line | Design tier model (ADR needed) | Eng |
| L8 | AI-assisted diagnostics not built | Medium | Must not be marketed | Product + safety design | Cory/Eng |
| L9 | Recall / service-bulletin intelligence not built | Medium | Must not be marketed | Data-source decision | Cory |
| L10 | Dispatch is rule-based, not AI | Medium (copy accuracy) | Site says "AI-assisted dispatch" | Change copy to "smart, rule-based dispatch suggestions" | Cory |
| L11 | Audit log misses invoice send/void/refund and role changes; no viewer | Medium | Weaker forensic trail for money events | Add audit rows + read endpoint | Eng |
| L12 | MFA optional for owner/admin | Medium | Account-takeover risk | Company MFA policy exists; consider default-on for owners | Eng |
| L13 | Rate limiter fails open if Redis is down | Medium | Brute-force window during Redis outage (lockout still applies) | Alert on the log event; consider fail-closed for login | Eng |
| L14 | No OpenTelemetry, Grafana, or Loki | Medium | Metrics/logs exist but no dashboards/tracing | Add once a host exists | Eng |
| L15 | No browser end-to-end (Playwright) suite | Medium | UI flows covered by component tests + API tests only | Add Playwright smoke in CI | Eng |
| L16 | Manual accessibility audit not done (jsx-a11y lint only) | Medium | WCAG conformance not claimed | Keyboard/screen-reader/contrast pass | Eng |
| L17 | Mobile store builds unsigned | Medium (mobile channel) | No App Store/Play release | Developer accounts + signing | Cory |
| L18 | Marketing site repo has CI but no enforced branch protection | Low | Site source now lives in private repo `coryelliott2016-eng/harboriq-marketing-site` with CI (type-check, API tests, build, claim guard, gitleaks); GitHub rulesets on private repos need GitHub Pro; Vercel is not yet Git-connected | Upgrade to GitHub Pro (or make the repo public), add ruleset `protect-main`; connect the repo in Vercel project settings | Cory |
| L19 | Marketing site uses hash routing (`/#/pricing`) | Low | Weaker SEO for deep pages | Switch to path routing with rewrites | Eng |
| L20 | Public investor page showed SAFE round terms | Needs counsel | Possible general-solicitation issue under Reg D 506(b) | Terms, EIN, allocations and use of funds removed from the page, meta, and site assistant in the site repo (CI blocks re-adding them). **Not yet live**: Vercel deploy from this environment fails TLS verification; deploy from the repo. Counsel review still required before any public promotion | Cory |
| L21 | Estimate send commits status before issuing the portal token/email | Low | Rare failure leaves estimate "sent" without an email; staff can re-send portal invite | Accepted; documented in ADR 0004 | Eng |
| L22 | Migration 0024 downgrade is lossy (fractional quantities rounded) | Low | Only on rollback | Take a backup before upgrading production | Eng |
| L23 | Crypto payments and asset tokenization code exists but is disabled | Info | None while flags are off | Keep off pending legal review | Cory |
| L24 | No third-party penetration test; no certifications | Info | Must not claim SOC 2/ISO/PCI | Commission a pen test before scaling | Cory |
| L25 | Terms/Privacy acceptance is enforced only in the signup UI; the API does not require or record it | Medium (legal evidence) | No server-side record of consent timestamp/version | Review draft PR #54 (adds the API contract) and add a stored `terms_accepted_at` + version | Eng |
