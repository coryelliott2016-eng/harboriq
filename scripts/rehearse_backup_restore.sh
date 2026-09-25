#!/usr/bin/env bash
#
# rehearse_backup_restore.sh — end-to-end verification that a backup taken
# by scripts/backup_db.sh can actually be restored by scripts/restore_db_s3.sh.
#
# An untested backup is not a backup. This script exists so that verifying
# "yes, our backups round-trip" is a single command an operator (or CI) can
# run, and so tests/test_backup_restore_rehearsal.py can execute it as a
# blocking gate in CI's `test` job. The gate is deliberately a full
# scripts/backup_db.sh + scripts/restore_db_s3.sh round trip rather than a
# unit test of either one alone, because the class of failure this exists
# to catch (a dump that psql refuses to reload because pg_dump emitted
# something ON_ERROR_STOP rejects, a missing extension on the restore side,
# a schema-search-path mismatch, etc.) only shows up on the seam between
# the two.
#
# What the rehearsal does, in order:
#   1. Dump the SOURCE database via scripts/backup_db.sh to a temp dir.
#   2. Create a scratch RESTORE database (name embeds "rehearsal" so
#      restore_db_s3.sh's production-shape guard is satisfied without
#      RESTORE_CONFIRM).
#   3. Restore the dump into the scratch DB via scripts/restore_db_s3.sh.
#   4. Verify the round trip:
#        (a) The `alembic_version` table exists and matches the source's
#            current head (schema round-tripped).
#        (b) A representative set of tenant-scoped tables has the same row
#            count in source and restored (data round-tripped).
#   5. Drop the scratch DB and clean the temp dir on exit, whether or not
#      the rehearsal passed. The whole run is idempotent so CI can invoke
#      it every push without needing a "clean previous rehearsal" step.
#
# Environment variables:
#
#   REHEARSAL_ADMIN_URL   REQUIRED. Superuser-or-CREATEDB connection URL
#                         used to create and drop the scratch database.
#                         Its dbname is treated as the maintenance DB, so
#                         `postgres` or `template1` works.
#   REHEARSAL_SOURCE_URL  REQUIRED. Connection URL for the source database
#                         to back up. Read-only from this script's point of
#                         view; nothing is written here.
#   REHEARSAL_SCRATCH_DB  Optional. Name of the scratch DB to create for
#                         the restore. Default:
#                         harboriq_rehearsal_$(date +%s). MUST contain
#                         "rehearsal" (enforced below) so
#                         restore_db_s3.sh's production-shape guard passes.
#
# Exit codes:
#   0   Round-trip succeeded.
#   2   Precondition failure (missing env, missing tool, bad scratch name).
#   3   Backup step failed.
#   4   Scratch DB creation failed.
#   5   Restore step failed.
#   6   Verification step failed (schema or row-count mismatch).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${REHEARSAL_ADMIN_URL:?rehearse_backup_restore.sh: REHEARSAL_ADMIN_URL is required}"
: "${REHEARSAL_SOURCE_URL:?rehearse_backup_restore.sh: REHEARSAL_SOURCE_URL is required}"

REHEARSAL_SCRATCH_DB="${REHEARSAL_SCRATCH_DB:-harboriq_rehearsal_$(date +%s)}"

# Normalize SQLAlchemy-style URL schemes (`postgresql+psycopg://`,
# `postgresql+asyncpg://`, ...) to the plain `postgresql://` libpq scheme
# that `psql` and `pg_dump` actually understand. The rest of the codebase
# stores DB URLs in SQLAlchemy form because that's what the app driver
# needs, so accepting them here and stripping the driver suffix is much
# less surprising than forcing every caller to remember to rewrite it.
# Without this, pg_dump silently ignores the URL (unknown scheme), falls
# back to a unix-socket default, and fails with "connection to server on
# socket ... failed" in CI where Postgres is a TCP-only service container.
normalize_libpq_url() {
  python3 - "$1" <<'PY'
import sys, urllib.parse
url = sys.argv[1]
p = urllib.parse.urlsplit(url)
scheme = p.scheme
if "+" in scheme:
    scheme = scheme.split("+", 1)[0]
if scheme == "postgres":
    scheme = "postgresql"
print(urllib.parse.urlunsplit((scheme, p.netloc, p.path, p.query, p.fragment)))
PY
}
REHEARSAL_ADMIN_URL="$(normalize_libpq_url "$REHEARSAL_ADMIN_URL")"
REHEARSAL_SOURCE_URL="$(normalize_libpq_url "$REHEARSAL_SOURCE_URL")"

# Guard: the scratch DB name has to include "rehearsal" so restore_db_s3.sh
# treats it as a safe target without RESTORE_CONFIRM. If a caller overrides
# REHEARSAL_SCRATCH_DB with something that doesn't match, fail loudly here
# rather than have restore_db_s3.sh refuse midway.
case "$REHEARSAL_SCRATCH_DB" in
  *rehearsal*|*scratch*|*restore*|*test*) : ;;
  *)
    echo "rehearse_backup_restore.sh: REHEARSAL_SCRATCH_DB must contain 'rehearsal', 'scratch', 'restore', or 'test' (got: ${REHEARSAL_SCRATCH_DB})" >&2
    exit 2
    ;;
esac

command -v psql >/dev/null 2>&1 || { echo "rehearse_backup_restore.sh: psql not found" >&2; exit 2; }
command -v pg_dump >/dev/null 2>&1 || { echo "rehearse_backup_restore.sh: pg_dump not found" >&2; exit 2; }

# Build the scratch DB URL by replacing the dbname in REHEARSAL_ADMIN_URL.
# We do this in Python (already a repo dep) rather than fragile sed so a
# URL with query-string / user-info / port variations still parses.
scratch_url_for() {
  local db_name="$1"
  python3 - "$REHEARSAL_ADMIN_URL" "$db_name" <<'PY'
import sys, urllib.parse
admin_url, db_name = sys.argv[1], sys.argv[2]
p = urllib.parse.urlsplit(admin_url)
new = p._replace(path="/" + db_name)
print(urllib.parse.urlunsplit(new))
PY
}

REHEARSAL_SCRATCH_URL="$(scratch_url_for "$REHEARSAL_SCRATCH_DB")"

WORKDIR="$(mktemp -d)"
BACKUPS_DIR="${WORKDIR}/backups"
mkdir -p "$BACKUPS_DIR"

cleanup() {
  local exit_code=$?
  # Best-effort scratch DB drop. Never let cleanup failure mask the real
  # exit code of the rehearsal itself.
  set +e
  psql "$REHEARSAL_ADMIN_URL" --set ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS \"${REHEARSAL_SCRATCH_DB}\" WITH (FORCE);" \
    >/dev/null 2>&1
  rm -rf "$WORKDIR"
  set -e
  exit "$exit_code"
}
trap cleanup EXIT

echo "rehearse_backup_restore.sh: step 1/5 — dump source"
# BACKUP_DATABASE_URL is passed to `pg_dump` directly, so it must already
# be in plain libpq form — normalize_libpq_url above has done that.
if ! BACKUP_DATABASE_URL="$REHEARSAL_SOURCE_URL" \
     BACKUP_OUTPUT_DIR="$BACKUPS_DIR" \
     BACKUP_RETENTION_DAYS=0 \
     "${SCRIPT_DIR}/backup_db.sh"; then
  echo "rehearse_backup_restore.sh: backup step failed" >&2
  exit 3
fi

# find, not glob-expansion, so an empty dir raises the right error rather
# than passing a literal "*.sql.gz" to psql later.
dump_file="$(find "$BACKUPS_DIR" -maxdepth 1 -name 'harboriq_*.sql.gz' -printf '%T@ %p\n' | sort -rn | head -n1 | cut -d' ' -f2-)"
if [ -z "$dump_file" ] || [ ! -f "$dump_file" ]; then
  echo "rehearse_backup_restore.sh: backup_db.sh reported success but produced no dump" >&2
  exit 3
fi
echo "rehearse_backup_restore.sh: dump = ${dump_file} ($(du -h "$dump_file" | cut -f1))"

echo "rehearse_backup_restore.sh: step 2/5 — create scratch database ${REHEARSAL_SCRATCH_DB}"
if ! psql "$REHEARSAL_ADMIN_URL" --set ON_ERROR_STOP=1 -c \
      "DROP DATABASE IF EXISTS \"${REHEARSAL_SCRATCH_DB}\" WITH (FORCE);" >/dev/null; then
  echo "rehearse_backup_restore.sh: DROP DATABASE failed" >&2
  exit 4
fi
if ! psql "$REHEARSAL_ADMIN_URL" --set ON_ERROR_STOP=1 -c \
      "CREATE DATABASE \"${REHEARSAL_SCRATCH_DB}\";" >/dev/null; then
  echo "rehearse_backup_restore.sh: CREATE DATABASE failed" >&2
  exit 4
fi

# Some HarborIQ migrations depend on extensions (pgcrypto, citext,
# btree_gist) that the migration role cannot install on its own; the base
# `docker-entrypoint-initdb.d/00_roles.sql` installs them into the default
# `harboriq` database, but a freshly-created scratch database has none.
# Install them here as the admin role before restoring, so the dump's
# CREATE TABLE ... on top of them succeeds.
echo "rehearse_backup_restore.sh: seeding scratch DB with required extensions"
psql "$REHEARSAL_SCRATCH_URL" --set ON_ERROR_STOP=1 -c \
  "CREATE EXTENSION IF NOT EXISTS pgcrypto; \
   CREATE EXTENSION IF NOT EXISTS citext; \
   CREATE EXTENSION IF NOT EXISTS btree_gist;" >/dev/null

echo "rehearse_backup_restore.sh: step 3/5 — restore into scratch"
if ! RESTORE_DATABASE_URL="$REHEARSAL_SCRATCH_URL" \
     "${SCRIPT_DIR}/restore_db_s3.sh" "$dump_file"; then
  echo "rehearse_backup_restore.sh: restore step failed" >&2
  exit 5
fi

echo "rehearse_backup_restore.sh: step 4/5 — verify schema (alembic_version)"
src_head="$(psql "$REHEARSAL_SOURCE_URL" -Atqc "SELECT version_num FROM alembic_version;" 2>/dev/null || true)"
dst_head="$(psql "$REHEARSAL_SCRATCH_URL" -Atqc "SELECT version_num FROM alembic_version;" 2>/dev/null || true)"
if [ -z "$src_head" ]; then
  echo "rehearse_backup_restore.sh: source has no alembic_version row (are migrations applied?)" >&2
  exit 6
fi
if [ "$src_head" != "$dst_head" ]; then
  echo "rehearse_backup_restore.sh: alembic_version mismatch — source=${src_head} restored=${dst_head:-<empty>}" >&2
  exit 6
fi
echo "rehearse_backup_restore.sh: alembic_version = ${src_head} (matches)"

echo "rehearse_backup_restore.sh: step 5/5 — verify row counts on core tables"
# Deliberately a small, hard-coded list of tables we know exist in every
# HarborIQ schema past Phase 1 (companies + users + sessions are the auth
# core). Not every table, because a full row-count diff on 60+ tables
# would trip on `outbox_events` / `stripe_processed_events` / audit-log
# rows written between the pg_dump and the source-side count query — for
# THIS check we want tables where inflight writes are unlikely.
core_tables=(companies users user_sessions)
for t in "${core_tables[@]}"; do
  src_count="$(psql "$REHEARSAL_SOURCE_URL" -Atqc "SELECT COUNT(*) FROM ${t};" 2>/dev/null || true)"
  dst_count="$(psql "$REHEARSAL_SCRATCH_URL" -Atqc "SELECT COUNT(*) FROM ${t};" 2>/dev/null || true)"
  if [ -z "$src_count" ]; then
    echo "rehearse_backup_restore.sh: source has no table '${t}' — schema shape unexpected" >&2
    exit 6
  fi
  if [ "$src_count" != "$dst_count" ]; then
    echo "rehearse_backup_restore.sh: ${t} row-count mismatch — source=${src_count} restored=${dst_count:-<empty>}" >&2
    exit 6
  fi
  echo "rehearse_backup_restore.sh: ${t} = ${src_count} rows (matches)"
done

echo "rehearse_backup_restore.sh: PASS — backup round-trips cleanly"
