#!/usr/bin/env bash
#
# backup_db.sh — pg_dump wrapper for a host cron job.
#
# Not a managed-backup-service integration (S3 lifecycle rules, point-in-time
# recovery via WAL archiving, cross-region replication, etc.) — that is out
# of scope for this script. This is the honest, minimal thing a single-host
# pilot deployment actually needs: a correct, runnable, timestamped
# `pg_dump` on a schedule, plus a retention sweep so the output directory
# does not grow unbounded. Off-host copies of the resulting file (rclone/
# rsync to S3 or another host, etc.) are the operator's responsibility —
# see docs/DEPLOYMENT.md, "Backups", for the recommended next step.
#
# Usage:
#   ./scripts/backup_db.sh
#
# Configuration is via environment variables (all optional, sensible
# defaults for the local/dev connection details already used elsewhere in
# this repo — override every one of them for a real deployment):
#
#   BACKUP_DATABASE_URL   Full libpq connection string to dump. Defaults to
#                         this repo's DATABASE_URL convention pointed at the
#                         `harboriq_service` role (BYPASSRLS), since a
#                         backup must capture every tenant's rows, not just
#                         whatever the RLS-scoped app role could see even if
#                         it were used here (harboriq_app has no bypass and
#                         no current_company_id session var set for a batch
#                         job, so it would see nothing at all).
#   BACKUP_OUTPUT_DIR     Directory dumps are written to. Default: ./backups
#   BACKUP_RETENTION_DAYS How many days of dumps to keep on disk before this
#                         script deletes them itself. Default: 14. Set to 0
#                         to disable pruning entirely.
#
# Suggested cron entry (daily at 02:15, output dir on a separate volume from
# the DB's own data directory so a full disk on one does not take out both):
#
#   15 2 * * * BACKUP_OUTPUT_DIR=/var/backups/harboriq \
#     /opt/harboriq/scripts/backup_db.sh >> /var/log/harboriq-backup.log 2>&1
#
# Restore (destructive — restores into whatever database the connection
# string in $BACKUP_DATABASE_URL points at):
#
#   gunzip -c backups/harboriq_20260101T021500Z.sql.gz | psql "$DATABASE_URL"

set -euo pipefail

BACKUP_DATABASE_URL="${BACKUP_DATABASE_URL:-${SERVICE_DATABASE_URL:-postgresql://harboriq_service:harboriq_service_pass@localhost:5432/harboriq}}"
BACKUP_OUTPUT_DIR="${BACKUP_OUTPUT_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

command -v pg_dump >/dev/null 2>&1 || {
  echo "backup_db.sh: pg_dump not found on PATH (install postgresql-client)" >&2
  exit 1
}

mkdir -p "$BACKUP_OUTPUT_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
outfile="${BACKUP_OUTPUT_DIR}/harboriq_${timestamp}.sql.gz"
tmpfile="${outfile}.partial"

echo "backup_db.sh: dumping to ${outfile}"

# --no-owner/--no-privileges: a restore target's roles (harboriq_app,
# harboriq_service) may not exist yet or may have different names/passwords
# on the restore host — the schema/data should not fail to restore over
# that. --format=plain (the default) piped through gzip keeps this legible
# with zero extra tooling on the restore side (`gunzip -c ... | psql`)
# rather than requiring pg_restore + the custom format's toolchain.
#
# Write to a .partial name first and rename on success, so a crashed or
# killed backup never leaves a truncated file that looks like a complete,
# restorable dump.
pg_dump "$BACKUP_DATABASE_URL" \
  --no-owner \
  --no-privileges \
  | gzip > "$tmpfile"

mv "$tmpfile" "$outfile"
echo "backup_db.sh: wrote $(du -h "$outfile" | cut -f1) to ${outfile}"

if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
  echo "backup_db.sh: pruning dumps older than ${BACKUP_RETENTION_DAYS} days in ${BACKUP_OUTPUT_DIR}"
  find "$BACKUP_OUTPUT_DIR" -maxdepth 1 -name 'harboriq_*.sql.gz' -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete
fi

echo "backup_db.sh: done"
