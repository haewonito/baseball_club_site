#!/usr/bin/env bash
# Restore a dump made by scripts/backup_prod.sh.
#
# Usage:
#   scripts/restore_backup.sh local <dump.sql.gz> [dbname]
#       Restore into a local database (default: baseball_club_restore), dropping
#       and recreating it first. Use this to inspect old data or to rehearse a
#       migration against real data:
#           DATABASE_URL=postgres://localhost/baseball_club_restore python manage.py migrate
#       Restoring over your dev database (baseball_club) asks for confirmation.
#
#   scripts/restore_backup.sh prod <dump.sql.gz>
#       Replace the ENTIRE production database with the dump. Everything written
#       since that dump is lost. It takes a fresh backup first (so the restore
#       itself can be undone), asks you to type a confirmation, and runs as one
#       transaction: if anything fails, prod is left exactly as it was.
#       Uploaded files on R2 are not touched.
#
# RESTORE_PROD_DATABASE overrides the target database on the prod Postgres server
# (default: railway, the one the app uses). It's only meant for testing this
# script against a scratch database.
set -euo pipefail

usage() { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

[ $# -ge 2 ] || usage
target=$1
dump=$2
[ -f "$dump" ] || { echo "No such file: $dump" >&2; exit 1; }

# Same checks backup_prod.sh makes, so a truncated file never gets restored.
gzip -t "$dump" 2>/dev/null || { echo "Not a complete gzip file: $dump" >&2; exit 1; }
gunzip -c "$dump" | grep -q 'PostgreSQL database dump complete' \
  || { echo "Dump is missing its completion marker (truncated?): $dump" >&2; exit 1; }

# The SQL to run: wipe the public schema, then replay the dump. The dump is plain
# SQL made with --no-owner/--no-privileges and doesn't create the public schema
# itself. transaction_timeout is a Postgres 17+ setting that prod's pg_dump emits;
# dropping it lets the dump load into local Postgres 16 with ON_ERROR_STOP on.
restore_sql() {
  echo 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'
  gunzip -c "$dump" | grep -v '^SET transaction_timeout'
}

confirm() {  # confirm <phrase>
  read -r -p "Type '$1' to continue: " reply || reply=
  [ "$reply" = "$1" ] || { echo "Aborted; nothing changed."; exit 1; }
}

case $target in
  local)
    db=${3:-baseball_club_restore}
    if [ "$db" = baseball_club ]; then
      echo "This replaces your local dev database '$db' with $dump."
      confirm "restore $db"
    fi
    dropdb --if-exists "$db"
    createdb "$db"
    restore_sql | psql -q -v ON_ERROR_STOP=1 --single-transaction -d "$db" >/dev/null \
      || { echo "Restore FAILED; '$db' was rolled back to empty." >&2; exit 1; }
    echo "Restored $dump into local database '$db'."
    ;;

  prod)
    db=${RESTORE_PROD_DATABASE:-railway}
    cd "$(git rev-parse --show-toplevel)"  # railway CLI link is per-directory
    echo "About to REPLACE production database '$db' with:"
    echo "  $dump ($(du -h "$dump" | cut -f1), modified $(date -r "$dump" '+%Y-%m-%d %H:%M'))"
    echo "Anything written to prod after that dump was taken will be lost."
    echo
    echo "Taking a safety backup of prod as it is now..."
    scripts/backup_prod.sh
    echo
    confirm "restore prod"
    restore_sql | railway ssh --service Postgres -- \
      psql -q -v ON_ERROR_STOP=1 --single-transaction -d "$db" >/dev/null \
      || { echo "Restore FAILED and was rolled back; prod is unchanged." >&2; exit 1; }
    echo "Restored $dump into production database '$db'."
    echo "If the dump predates a migration that's deployed now, run migrations:"
    echo "  railway ssh -- python manage.py migrate"
    ;;

  *) usage ;;
esac
