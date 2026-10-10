# Pilot deployment on Render + Neon

Status as of 2026-09-22. This is the chosen pilot host. `DEPLOYMENT.md` (Docker
Compose on a VM) remains the documented alternative.

## Why this shape

| Concern | Choice | Reason |
|---|---|---|
| Postgres | Neon project `harboriq-app-production` (`still-brook-30739192`, AWS us-east-1, PG 17) | Managed backups/branching; supports the two-role RLS model (verified below) |
| API | Render web service `harboriq-api` (Docker, `Dockerfile`) | Same image CI already builds; health check `/api/v1/healthz`; migrations run as `preDeployCommand` |
| Jobs | Render worker `harboriq-worker` (`celery worker -B`) | One process runs worker + beat; exactly one instance must run |
| Redis | Render Key Value `harboriq-redis`, `noeviction`, private only | Celery broker must not drop jobs |
| Web app | Render static site `harboriq-app`, `/api/*` rewritten to the API | Same origin, so the refresh/CSRF cookies work (`onrender.com` subdomains are cross-site to each other) |

Everything is declared in `render.yaml`. Secrets are `sync: false` or
`generateValue: true`; none are committed.

## Done (2026-09-22)

- Neon project created on the free plan. Roles:
  - `harboriq_app`: `NOBYPASSRLS`, used by the API (`DATABASE_URL`, pooled endpoint).
  - `harboriq_service`: `BYPASSRLS`, table owner, used for migrations and platform ops (`SERVICE_DATABASE_URL`, direct endpoint).
  - Extensions `pgcrypto`, `citext`, `btree_gist` installed.
- `alembic upgrade head` applied: schema at revision `0025`, 36 tables.
- Connection strings are held outside the repo and will be entered into Render as secrets.

## Remaining steps

1. Copy `.env.example` to `.env`, fill production values, and run:
   `python scripts/cloud_deploy_preflight.py --env-file .env`
   If off-host AWS backups are enabled, either set `AWS_BACKUP_ENABLED=true` in
   `.env` or append `--require-aws-backups` for this check.
2. Connect Render to Computer (or in the Render dashboard, create **New > Blueprint** from this repo).
3. Enter the `sync: false` values: the two database URLs, `MFA_ENCRYPTION_KEY` (Fernet), `APP_BASE_URL`, `CORS_ALLOW_ORIGINS`, Stripe **test** keys, SMTP settings.
4. Deploy API + worker + Redis + static site from `render.yaml`.
5. Run `HARBORIQ_BASE_URL=https://harboriq-app.onrender.com python smoke_test.py` and the manual checklist in `TESTING_QA_PLAN.md`.
6. After harboriq.com DNS is recovered: add `app.harboriq.com` as a custom domain on `harboriq-app` and `api.harboriq.com` on `harboriq-api`, then update `APP_BASE_URL`/`CORS_ALLOW_ORIGINS` and the rewrite destination.

## "Cloud base" scope

HarborIQ treats "cloud base" as the **edge/CDN/WAF provider in front of the
Render origin**, not the app runtime itself. Runtime is locked to Render +
Neon (`DEPLOY_TARGET_STACK=render-neon`).

- `CLOUD_BASE_PROVIDER=cloudflare` means configure DNS/SSL/cache/WAF using
  `scripts/provision_cloudflare.py` and `docs/DEPLOYMENT.md`'s Cloudflare
  section.
- `CLOUD_BASE_PROVIDER=firebase|other|none` means skip Cloudflare provisioning
  and document the alternative edge choice in release notes before go-live.

## Cost (list prices, checked 2026-09-22)

About $24/month for the minimum setup: API $7, worker $7, Key Value $10, static site free ([Render pricing](https://render.com/pricing)). Neon's free plan includes 0.5 GB storage and 100 CU-hours per project. An always-on 0.25 CU compute uses about 180 CU-hours a month, so expect the metered Launch plan ($0.106 per CU-hour, about $19/month) once traffic is steady ([Neon pricing](https://neon.com/pricing)).

## Known gaps

- Neon free-plan backups are limited to a 6-hour history window. Move to a paid plan before real customer data is stored.
- No OpenTelemetry, Grafana, or Loki (L14). Render logs and Sentry (once `SENTRY_DSN` is set) are the only observability.

## Public marketing preview (controlled release only)

The default Render static site remains the authenticated application. A
**separate** static-site preview can build this repository's marketing candidate
with root directory `frontend`, build command `npm ci && npm run build:marketing`,
and publish directory `dist`. Preserve the existing `/api/*` proxy to the
authorized API origin and the SPA fallback. On hosts supporting clean directory
URLs, serve the generated `/ai-demo/index.html`, `/contact/index.html`, and
`/demo-disclosure/index.html` before the fallback.

- Set `VITE_API_URL=/` for a same-origin API proxy, or an approved HTTPS API
  origin with CORS configured for the preview. Never put provider keys in
  `VITE_*` variables.
- Leave `VITE_PUBLIC_SITE_URL` unset on previews: generated robots and metadata
  disable indexing. Set it to an owner-verified HTTPS marketing origin only
  after domain/deployment approval; that enables canonical URLs and the sitemap.
- The existing Terms/Privacy links use `VITE_MARKETING_SITE_URL`; verify those
  pages and obtain legal approval before collecting real leads. The technical
  demo disclosure is not a substitute for reviewed legal policies.
- Configure Redis and a dedicated demo signing secret on the API before testing
  anonymous sessions. No inference credentials are accepted by this candidate,
  because no verified engine exists in this checkout.
- Apply existing migrations for `marketing_leads`. Configure and verify SMTP,
  `MARKETING_LEAD_NOTIFY_TO`, and admin access separately. A database commit
  does not certify email delivery.
- Validate trusted proxy handling so request client addresses reflect the real
  caller, and add managed edge bot/WAF protection before public rollout. Do not
  trust arbitrary client-supplied forwarded headers.

Neither `harboriq.com` nor the documented external Vercel hostname could be
resolved from the implementation environment. No active deployment, preview URL,
custom-domain binding, or live model/lead delivery was verified. No production
deployment was performed. Obtain the existing marketing project source and host
access before migration; retain manual release approval and the cloud preflight.
Production remains blocked on verified AI integration, legal/privacy review,
working domain/proxy configuration, configured lead storage/notifications, edge
bot mitigation, and a successful preview acceptance run.
