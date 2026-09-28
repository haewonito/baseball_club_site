#!/usr/bin/env bash
# Dump the production Postgres database to backups/prod-<timestamp>.sql.gz.
#
# pg_dump runs *inside* the Railway Postgres container (via `railway ssh`) and
# streams back, so it needs neither the public TCP proxy nor a local pg_dump
# that matches the server's major version (prod is Postgres 18, local is 16).
#
# Usage (from anywhere in the repo; needs the Railway CLI linked to this project):
#   scripts/backup_prod.sh
#
# Restore into a throwaway local DB (e.g. to rehearse a migration):
#   createdb baseball_restore
#   gunzip -c backups/prod-<timestamp>.sql.gz | psql -q -d baseball_restore
# An 'unrecognized configuration parameter "transaction_timeout"' error there is
# harmless: it's a Postgres 17+ setting that a local Postgres 16 doesn't know.
#
# Backups contain families' personal data -- backups/ is gitignored; keep them private.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
mkdir -p backups
chmod 700 backups

out="backups/prod-$(date +%Y-%m-%d-%H%M%S).sql.gz"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT

echo "Dumping production database..."
railway ssh --service Postgres -- \
  sh -c 'set -o pipefail 2>/dev/null; pg_dump --no-owner --no-privileges | gzip -c' > "$tmp"

# A dropped connection can leave a truncated file that still looks fine at a
# glance, so check both the gzip stream and pg_dump's own end-of-dump marker.
if ! gzip -t "$tmp" 2>/dev/null; then
  echo "Backup FAILED: output is not a complete gzip file." >&2
  exit 1
fi
if ! gunzip -c "$tmp" | grep -q 'PostgreSQL database dump complete'; then
  echo "Backup FAILED: dump is missing its completion marker (truncated?)." >&2
  exit 1
fi

chmod 600 "$tmp"
mv "$tmp" "$out"
echo "Backup written: $out ($(du -h "$out" | cut -f1))"
