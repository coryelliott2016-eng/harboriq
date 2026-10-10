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

## In-repository public experience (not deployed)

The repository now contains a replacement **candidate**, not an update to the
externally hosted Vercel source. `frontend/src/marketing/` provides a public
homepage, `/ai-demo`, `/contact`, and `/demo-disclosure`. Build it separately with
`cd frontend && npm ci && npm run build:marketing`. The default app build retains
its authenticated dashboard at `/`; its public preview is at `/explore`.
The marketing build does not mount staff authentication or register a service
worker. Do not replace the app's Render deployment with this build.

The API inspection found **no verified LLM provider, marine diagnostic inference,
RAG service, or predictive model in this checkout**. Rule-based dispatch is not a
conversational marine diagnostic engine. The public AI API therefore reports
unavailable and returns an explicit error rather than manufacturing an answer.
Suggested questions are interactive; a generated guided experience remains
blocked on an authorized, verified engine and knowledge-resource integration.
Connecting the external site's `/api/chat` requires its source, authorization,
and validation of isolation, provider configuration, and data provenance first.

Public requests use the existing FastAPI `/api/v1/public/` endpoints, with no
staff cookies or authorization headers. Contact capture reuses
`POST /api/v1/public/leads`: the UI confirms database acceptance only, not
notification delivery, a meeting booking, or a marketing subscription.
Aggregate measurement is opt-in for the current visit, restricted to named
events, and does not send chats or contact details. Full lead-to-customer
attribution and booking completion remain unimplemented.
