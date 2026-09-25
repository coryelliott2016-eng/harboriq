# ADR 0005 — Marketing site deployed separately; lead capture fails closed

Status: Accepted

## Context
The public site must be live before the SaaS host exists, and must never
pretend to capture a lead it cannot store.

## Decision
- The marketing site is a separate Vercel project (`harbor-iq/harboriq`),
  with its own serverless endpoints (`/api/health`, `/api/leads`, `/api/chat`).
- If `DATABASE_URL` is not configured, `POST /api/leads` returns 503 and the
  demo page shows an "online requests are temporarily unavailable — call us"
  message instead of a fake success. The assistant endpoint likewise returns
  503 without `ANTHROPIC_API_KEY`.

## Consequences
- No silent lead loss; but online lead capture is **off** until a lead
  database is connected in the Vercel project.
- The site's source currently lives in Perplexity Project files, not this
  repo; bringing it under this repo's CI is a follow-up.
