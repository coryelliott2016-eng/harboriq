#!/usr/bin/env bash
#
# restore_db_s3.sh — companion to backup_db_s3.sh.
#
# Restores a HarborIQ pg_dump (either an already-local *.sql.gz produced by
# backup_db.sh / backup_db_s3.sh, or one pulled fresh from S3) into a target
# PostgreSQL database. The whole point of this script existing separately
# from a one-liner in the runbook is that an untested backup is not a
# backup: the restore path has to be scripted, exercised in
# tests/test_backup_restore_rehearsal.py, and runnable by an operator
# during a real incident without them having to reconstruct the arguments
# to `psql` from docs at 3am.
#
# Safety model (matches the "never overwrite production without an explicit
# confirmation" pattern the rest of this repo already uses for destructive
# scripts):
#   - Refuses to run against a URL whose database name contains
#     "harboriq" and does NOT contain "test"/"scratch"/"rehearsal"/"restore"
#     unless RESTORE_CONFIRM=YES-I-KNOW-THIS-WILL-OVERWRITE-DATA is set in
#     the environment. This is a soft guardrail meant to stop a copy-paste
#     from `docs/DEPLOYMENT.md`'s example running against the real primary;
#     it is NOT a substitute for a proper access-control boundary on the
#     production role.
#   - Always uses `psql --set ON_ERROR_STOP=1` so a bad restore aborts
#     loudly rather than half-applies and returns 0.
#
# Usage:
#
#   # Restore a specific local dump into a scratch database:
#   RESTORE_DATABASE_URL=postgresql://.../harboriq_scratch \
#     ./scripts/restore_db_s3.sh ./backups/harboriq_20260814T021500Z.sql.gz
#
#   # Pull the newest dump from S3 first, then restore it:
#   RESTORE_DATABASE_URL=postgresql://.../harboriq_scratch \
#     BACKUP_S3_BUCKET=my-company-harboriq-backups \
#     ./scripts/restore_db_s3.sh --from-s3-latest
#
#   # Pull a specific S3 key:
#   RESTORE_DATABASE_URL=postgresql://.../harboriq_scratch \
#     BACKUP_S3_BUCKET=my-company-harboriq-backups \
#     ./scripts/restore_db_s3.sh --from-s3 \
#       harboriq-backups/harboriq_20260814T021500Z.sql.gz
#
# Environment variables:
#
#   RESTORE_DATABASE_URL    REQUIRED. Full libpq connection string of the
#                           database to restore INTO. Should point at a
#                           freshly-created empty database or a scratch
#                           database you are willing to clobber; existing
#                           tables with the same name will conflict.
#   RESTORE_CONFIRM         Required-only when RESTORE_DATABASE_URL looks
#                           production-shaped (see safety model above).
#   BACKUP_S3_BUCKET        Required when using --from-s3-latest / --from-s3.
#   BACKUP_S3_PREFIX        Key prefix inside the bucket. Default:
#                           "harboriq-backups" (matches backup_db_s3.sh).
#   BACKUP_S3_ENDPOINT_URL  Optional S3-compatible endpoint (R2/B2/MinIO);
#                           unset = real AWS S3.
#   RESTORE_WORKDIR         Where to stage a dump downloaded from S3.
#                           Default: a fresh mktemp -d.
#
# What this script deliberately does NOT do:
#   - Create the target database. `CREATE DATABASE` requires connecting to
#     `postgres`/`template1` as a superuser or a role with CREATEDB; the
#     operator (or the rehearsal script) does that step explicitly. This
#     script only restores INTO an already-existing target.
#   - Run Alembic migrations after restore. `pg_dump` captured whatever
#     schema was live at backup time, so post-restore the target already
#     has the exact schema the app expected. If a schema change has landed
#     on master since the dump was taken, run `alembic upgrade head`
#     against the restored DB as a separate step.
#   - Manage restore-target roles. `pg_dump --no-owner --no-privileges`
#     (backup_db.sh's convention) already strips owner/ACL metadata, so the
#     restore only needs the target role to have CREATE on the schema.

set -euo pipefail

usage() {
  sed -n '2,60p' "$0"
  exit "${1:-1}"
}

# --- Argument parsing ---------------------------------------------------

MODE=""
LOCAL_DUMP=""
S3_KEY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --from-s3-latest)
      MODE="s3-latest"
      shift
      ;;
    --from-s3)
      MODE="s3-key"
      shift
      if [ $# -eq 0 ]; then
        echo "restore_db_s3.sh: --from-s3 requires an S3 key argument" >&2
        exit 2
      fi
      S3_KEY="$1"
      shift
      ;;
    -h|--help)
      usage 0
      ;;
    -*)
      echo "restore_db_s3.sh: unknown flag: $1" >&2
      usage 2
      ;;
    *)
      if [ -z "$MODE" ]; then
        MODE="local"
        LOCAL_DUMP="$1"
      else
        echo "restore_db_s3.sh: unexpected positional argument: $1" >&2
        usage 2
      fi
      shift
      ;;
  esac
done

if [ -z "$MODE" ]; then
  echo "restore_db_s3.sh: must pass either a local dump path, --from-s3-latest, or --from-s3 <key>" >&2
  usage 2
fi

# --- Preconditions ------------------------------------------------------

: "${RESTORE_DATABASE_URL:?restore_db_s3.sh: RESTORE_DATABASE_URL is required}"

command -v psql >/dev/null 2>&1 || {
  echo "restore_db_s3.sh: psql not found on PATH (install postgresql-client)" >&2
  exit 1
}
command -v gunzip >/dev/null 2>&1 || {
  echo "restore_db_s3.sh: gunzip not found on PATH" >&2
  exit 1
}

# Production-shape guard: refuse to run against something that looks like a
# real HarborIQ database unless the operator explicitly acknowledges the
# risk. Matches the "scratch"/"test"/"rehearsal"/"restore" allow-list every
# consumer of this script (rehearsal, docs, CI) already uses.
lower_url="$(printf '%s' "$RESTORE_DATABASE_URL" | tr '[:upper:]' '[:lower:]')"
if [[ "$lower_url" == *harboriq* ]] \
   && [[ "$lower_url" != *test* ]] \
   && [[ "$lower_url" != *scratch* ]] \
   && [[ "$lower_url" != *rehearsal* ]] \
   && [[ "$lower_url" != *restore* ]]; then
  if [ "${RESTORE_CONFIRM:-}" != "YES-I-KNOW-THIS-WILL-OVERWRITE-DATA" ]; then
    echo "restore_db_s3.sh: RESTORE_DATABASE_URL looks like a real HarborIQ DB name" >&2
    echo "restore_db_s3.sh: refusing to restore without RESTORE_CONFIRM=YES-I-KNOW-THIS-WILL-OVERWRITE-DATA" >&2
    exit 3
  fi
  echo "restore_db_s3.sh: RESTORE_CONFIRM acknowledged — proceeding against a production-shaped target"
fi

# --- Source a dump file -------------------------------------------------

WORKDIR=""
cleanup_workdir() {
  if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
    rm -rf "$WORKDIR"
  fi
}
trap cleanup_workdir EXIT

case "$MODE" in
  local)
    if [ ! -f "$LOCAL_DUMP" ]; then
      echo "restore_db_s3.sh: local dump not found: $LOCAL_DUMP" >&2
      exit 4
    fi
    DUMP_FILE="$LOCAL_DUMP"
    ;;

  s3-latest|s3-key)
    : "${BACKUP_S3_BUCKET:?restore_db_s3.sh: BACKUP_S3_BUCKET is required for S3 modes}"
    command -v aws >/dev/null 2>&1 || {
      echo "restore_db_s3.sh: aws CLI not found on PATH (install awscli)" >&2
      exit 1
    }
    prefix="${BACKUP_S3_PREFIX:-harboriq-backups}"
    endpoint_args=()
    if [ -n "${BACKUP_S3_ENDPOINT_URL:-}" ]; then
      endpoint_args=(--endpoint-url "$BACKUP_S3_ENDPOINT_URL")
    fi

    if [ "$MODE" = "s3-latest" ]; then
      echo "restore_db_s3.sh: listing s3://${BACKUP_S3_BUCKET}/${prefix}/ for newest dump"
      # `aws s3 ls` returns lines like: "2026-08-14 02:15:00  1234 harboriq_....sql.gz"
      # We sort them and pick the newest by filename (backup_db.sh's name
      # embeds a UTC ISO-8601 timestamp so lexical sort equals chronological
      # sort — this is more robust than parsing `aws s3 ls`'s date column
      # since that format has varied across CLI versions).
      newest="$(aws "${endpoint_args[@]}" s3 ls "s3://${BACKUP_S3_BUCKET}/${prefix}/" \
        | awk '{print $NF}' \
        | grep -E '^harboriq_[0-9]{8}T[0-9]{6}Z\.sql\.gz$' \
        | sort \
        | tail -n1)"
      if [ -z "$newest" ]; then
        echo "restore_db_s3.sh: no harboriq_*.sql.gz found in s3://${BACKUP_S3_BUCKET}/${prefix}/" >&2
        exit 5
      fi
      S3_KEY="${prefix}/${newest}"
    fi

    WORKDIR="${RESTORE_WORKDIR:-$(mktemp -d)}"
    DUMP_FILE="${WORKDIR}/$(basename "$S3_KEY")"
    echo "restore_db_s3.sh: pulling s3://${BACKUP_S3_BUCKET}/${S3_KEY} to ${DUMP_FILE}"
    aws "${endpoint_args[@]}" s3 cp "s3://${BACKUP_S3_BUCKET}/${S3_KEY}" "$DUMP_FILE"
    ;;
esac

# --- Restore ------------------------------------------------------------

echo "restore_db_s3.sh: restoring ${DUMP_FILE} into ${RESTORE_DATABASE_URL%%\?*}"
# ON_ERROR_STOP=1 turns any SQL error into a hard failure. Without it psql
# happily continues past a duplicate-table error and exits 0, which is the
# exact class of silent-half-restore this script exists to prevent.
gunzip -c "$DUMP_FILE" | psql "$RESTORE_DATABASE_URL" --set ON_ERROR_STOP=1 --quiet

echo "restore_db_s3.sh: done"
