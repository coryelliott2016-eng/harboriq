# HarborIQ Operations Runbook

Scope: day-2 operation of the single-host Docker Compose deployment in
[`DEPLOYMENT.md`](DEPLOYMENT.md) and the Vercel marketing site. **As of
2026-09-22 no production application host exists (KNOWN_LIMITATIONS L1);**
the procedures below are ready to use the day one is provisioned.

Shorthand: `dc` = `docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## Release procedure

1. Open a PR into `master`. The `protect-master` ruleset requires
   `secret-scan`, `lint`, `test`, `frontend`, `docker-build` to pass on an
   up-to-date branch; direct pushes and force-pushes are rejected.
2. PR description states: summary, tests, migration(s), rollback.
3. Merge (squash or merge commit). Tag the merge commit `vX.Y.Z` and add a
   `CHANGELOG.md` entry.
4. On the host, **take a backup first** (`scripts/backup_db.sh` or
   `scripts/backup_db_s3.sh`).
5. `git fetch && git checkout vX.Y.Z && dc up -d --build`
6. `dc exec app alembic upgrade head`
7. Run the release smoke test in [`TESTING_QA_PLAN.md`](TESTING_QA_PLAN.md).
8. Record the deployed SHA and time in the release notes.

## Rollback procedure

| Situation | Action |
|---|---|
| Bad app code, no migration in the release | `git checkout <previous tag> && dc up -d --build`; re-run smoke test |
| Release included a migration that is backward compatible | Roll code back as above; leave schema in place (newer columns are ignored by older code) |
| Migration must be reversed | `dc exec app alembic downgrade <previous revision>` **then** roll code back. For v0.2.0: `alembic downgrade 0023` (0024 downgrade rounds fractional estimate quantities) |
| Data damage | Stop `app`/`worker`/`beat`; restore the pre-deploy backup with `scripts/restore_db_s3.sh` (see DEPLOYMENT.md "Database backups"); redeploy the matching tag |
| Marketing site regression | In Vercel → project `harboriq` → Deployments, "Promote to Production" on the previous good deployment (instant, no rebuild) |

## Monitoring and alerting (what to watch)

| Signal | Source | Alert when | First response |
|---|---|---|---|
| Liveness | `GET /api/v1/healthz` | non-200 for 2 min | `dc ps`, `dc logs app --tail 200` |
| Readiness | `GET /api/v1/readyz` | 503 | Check `db` container / managed Postgres status, connection limits |
| Error rate | Prometheus `http_requests_total{status=~"5.."}` via `/metrics` (bearer `METRICS_TOKEN`) | >2% of requests over 5 min | Find `request_id` in logs; Sentry if `SENTRY_DSN` set |
| Latency | `http_request_duration_seconds` | p95 > 1.5 s for 10 min | Check DB slow queries, worker backlog |
| Email backlog | `SELECT count(*) FROM outbox_events WHERE status='dead_letter'` | > 0 | Usually SMTP credentials; fix, then re-queue (DEPLOYMENT.md incident step 3) |
| Rate limiter degraded | log event `rate_limit.redis_unavailable_failing_open` | any | Restore Redis; login lockout still applies meanwhile |
| Stripe webhooks | Stripe dashboard → Webhooks → failures | any failure | Verify `STRIPE_WEBHOOK_SECRET`; Stripe retries automatically and processing is idempotent |
| Backups | backup job exit code / S3 object age | no new backup in 26 h | Run backup manually; check AWS credentials |
| Marketing site | `GET https://harboriq-gamma.vercel.app/api/health` | non-200 | Vercel deployment logs |

Dashboards (Grafana) and log aggregation (Loki) are not yet set up (L14);
until then use `dc logs` with `jq` and the Prometheus endpoint directly.

## Routine tasks

- Weekly: review Dependabot alerts and CI audit results; review dead-letter
  outbox rows; confirm last backup restored in the rehearsal job.
- Monthly: rotate `METRICS_TOKEN`; review user list per tenant for stale
  admins; test a restore to a scratch database.
- Per new engineer: GitHub access via PR-only workflow (ruleset has no
  bypass); least-privilege cloud roles; never share production `.env`.

## Secrets inventory (names only — never values)

`JWT_SECRET`, `MFA_ENCRYPTION_KEY`, `DATABASE_URL`, `SERVICE_DATABASE_URL`,
`REDIS_URL`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `SMTP_*`,
`SENTRY_DSN`, `METRICS_TOKEN`, Twilio and AWS backup credentials (see
`.env.example` and DEPLOYMENT.md for the authoritative list). Vercel
marketing project currently has only `ADMIN_TOKEN` set.
