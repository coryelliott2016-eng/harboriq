#!/usr/bin/env bash
#
# backup_db_s3.sh — backup_db.sh, plus an optional off-host push to S3.
#
# This wraps scripts/backup_db.sh (which does the actual pg_dump + gzip +
# local retention sweep, unchanged) and adds exactly one thing: pushing the
# resulting dump file to S3-compatible object storage when it's configured
# to. Graceful degradation is the whole point of this script existing
# separately from backup_db.sh rather than baking the S3 push directly into
# it — this repo's established pattern (see smtp_host / stripe_api_key /
# twilio_account_sid in app/core/config.py) is that an integration with an
# external paid service is opt-in via env vars and silently no-ops to a
# strictly-local behavior when unset, rather than failing a deploy that
# never asked for that integration in the first place. A single-host pilot
# deployment with no AWS account at all must still get a fully-working
# local backup out of this script with zero configuration.
#
# Usage:
#   ./scripts/backup_db_s3.sh
#
# Configuration is via environment variables, all optional:
#
#   (all of scripts/backup_db.sh's variables — BACKUP_DATABASE_URL,
#   BACKUP_OUTPUT_DIR, BACKUP_RETENTION_DAYS — are honored unchanged, since
#   this script sources that one to do the local dump.)
#
#   BACKUP_S3_BUCKET      S3 bucket name to push each dump to, e.g.
#                         "my-company-harboriq-backups". Matches
#                         app/core/config.py's `backup_s3_bucket` setting
#                         (that setting is documentation/discoverability
#                         only — this script reads the env var directly, it
#                         is not part of the FastAPI app). LEAVE UNSET to
#                         skip the S3 push entirely: the script still runs
#                         the local backup and exits 0.
#   BACKUP_S3_PREFIX      Key prefix under the bucket. Default:
#                         "harboriq-backups" (matches `backup_s3_prefix`'s
#                         default in app/core/config.py).
#   BACKUP_S3_ENDPOINT_URL
#                         Optional. Set this to point the AWS CLI at an
#                         S3-compatible provider other than AWS itself
#                         (Cloudflare R2, Backblaze B2, MinIO, etc.) — see
#                         docs/DEPLOYMENT.md, "Backups", for provider-
#                         specific notes. Unset means real AWS S3.
#
#   Standard AWS CLI credential env vars (AWS_ACCESS_KEY_ID,
#   AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, AWS_PROFILE, AWS_REGION) are
#   read by the `aws` CLI itself, not by this script — an attached IAM
#   instance/task role works too and needs none of them set explicitly.
#   This script does not invent its own credential handling; it defers
#   entirely to whatever `aws s3 cp` already does with the standard SDK
#   credential chain (env vars -> shared config/credentials files ->
#   instance/task metadata role).
#
# What this script deliberately does NOT do (see docs/DEPLOYMENT.md,
# "Backups", for the honest reasoning on each):
#   - Point-in-time recovery via continuous WAL archiving. A nightly
#     pg_dump only ever restores to the moment it was taken; true PITR
#     needs a WAL-archiving/base-backup tool (pgBackRest, WAL-G, or a
#     managed provider's built-in PITR) run continuously, not a cron'd
#     pg_dump. Documented as a managed-hosting-provider feature to adopt
#     when the business needs an RPO tighter than "up to 24 hours old."
#   - S3 lifecycle rules (e.g. transition to Glacier after 30 days, expire
#     after 1 year) — configure those on the bucket itself (console,
#     Terraform, or `aws s3api put-bucket-lifecycle-configuration`); this
#     script only ever PUTs objects, it does not manage bucket policy.
#   - Cross-region replication, bucket creation, or IAM policy setup — all
#     one-time infrastructure setup, not a per-run backup-script concern.
#
# Suggested cron entry (daily at 02:15 — same slot backup_db.sh's own
# docstring suggests, since this replaces that entry, not adds to it):
#
#   15 2 * * * BACKUP_OUTPUT_DIR=/var/backups/harboriq \
#     BACKUP_S3_BUCKET=my-company-harboriq-backups \
#     /opt/harboriq/scripts/backup_db_s3.sh >> /var/log/harboriq-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKUP_OUTPUT_DIR="${BACKUP_OUTPUT_DIR:-./backups}"
BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-harboriq-backups}"

# Step 1: the real local backup. Unchanged behavior, unchanged script —
# every existing deployment already using backup_db.sh directly keeps
# working exactly as before if it never adopts this wrapper.
"${SCRIPT_DIR}/backup_db.sh"

if [ -z "$BACKUP_S3_BUCKET" ]; then
  echo "backup_db_s3.sh: BACKUP_S3_BUCKET not set, skipping S3 push (local-only backup)"
  exit 0
fi

command -v aws >/dev/null 2>&1 || {
  echo "backup_db_s3.sh: BACKUP_S3_BUCKET is set but the AWS CLI ('aws') was not found on PATH." >&2
  echo "backup_db_s3.sh: local backup above still succeeded; install awscli to enable the S3 push." >&2
  exit 1
}

# Find the dump backup_db.sh just wrote: the newest *.sql.gz in the output
# dir, not a name reconstructed from today's timestamp — reconstructing it
# would silently diverge if backup_db.sh's naming convention ever changes.
latest_dump="$(find "$BACKUP_OUTPUT_DIR" -maxdepth 1 -name 'harboriq_*.sql.gz' -printf '%T@ %p\n' 2>/dev/null \
  | sort -rn | head -n1 | cut -d' ' -f2-)"

if [ -z "$latest_dump" ]; then
  echo "backup_db_s3.sh: no harboriq_*.sql.gz found in ${BACKUP_OUTPUT_DIR} after running backup_db.sh — not pushing anything" >&2
  exit 1
fi

dump_basename="$(basename "$latest_dump")"
s3_uri="s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/${dump_basename}"

endpoint_args=()
if [ -n "${BACKUP_S3_ENDPOINT_URL:-}" ]; then
  endpoint_args=(--endpoint-url "$BACKUP_S3_ENDPOINT_URL")
fi

echo "backup_db_s3.sh: pushing ${latest_dump} to ${s3_uri}"
aws s3 cp "${endpoint_args[@]}" "$latest_dump" "$s3_uri"
echo "backup_db_s3.sh: done"
