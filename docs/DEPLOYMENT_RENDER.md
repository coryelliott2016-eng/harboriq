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

1. Connect Render to Computer (or in the Render dashboard, create **New > Blueprint** from this repo).
2. Enter the `sync: false` values: the two database URLs, `MFA_ENCRYPTION_KEY` (Fernet), `APP_BASE_URL`, `CORS_ALLOW_ORIGINS`, Stripe **test** keys, SMTP settings.
3. Deploy. Then run `HARBORIQ_BASE_URL=https://harboriq-app.onrender.com python smoke_test.py` and the manual checklist in `TESTING_QA_PLAN.md`.
4. After harboriq.com DNS is recovered: add `app.harboriq.com` as a custom domain on `harboriq-app` and `api.harboriq.com` on `harboriq-api`, then update `APP_BASE_URL`/`CORS_ALLOW_ORIGINS` and the rewrite destination.

## Cost (list prices, checked 2026-09-22)

About $24/month for the minimum setup: API $7, worker $7, Key Value $10, static site free ([Render pricing](https://render.com/pricing)). Neon's free plan includes 0.5 GB storage and 100 CU-hours per project. An always-on 0.25 CU compute uses about 180 CU-hours a month, so expect the metered Launch plan ($0.106 per CU-hour, about $19/month) once traffic is steady ([Neon pricing](https://neon.com/pricing)).

## Known gaps

- Neon free-plan backups are limited to a 6-hour history window. Move to a paid plan before real customer data is stored.
- No OpenTelemetry, Grafana, or Loki (L14). Render logs and Sentry (once `SENTRY_DSN` is set) are the only observability.
