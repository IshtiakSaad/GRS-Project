#!/usr/bin/env bash
# Prove the latest backup restores: load it into a scratch database, compare row counts
# with the live database, verify the audit hash chain in the copy, then drop the copy.
#   deploy/scripts/restore-check.sh [dump-file]
# An untested backup is a hope, not a backup.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

DIR="${BACKUP_DIR:-/var/backups/grs}"
FILE="${1:-$(ls -1t "$DIR"/grs-*.dump | head -1)}"
SCRATCH="grs_restore_check"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ -f docker-compose.prod.yml ] && [ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.prod" ] \
  || COMPOSE="docker compose"
PSQL="$COMPOSE exec -T postgres psql -U $POSTGRES_USER -v ON_ERROR_STOP=1 -qtA"

$PSQL -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH"
$PSQL -d postgres -c "CREATE DATABASE $SCRATCH"
trap '$PSQL -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null' EXIT

$COMPOSE exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$SCRATCH" --no-owner --exit-on-error < "$FILE"

count() { $PSQL -d "$1" -c "SELECT (SELECT count(*) FROM service_request) || '/' || (SELECT count(*) FROM audit_log) || '/' || (SELECT count(*) FROM app_user)"; }
LIVE=$(count "$POSTGRES_DB")
COPY=$(count "$SCRATCH")
echo "requests/audit rows/users  live=$LIVE  restored=$COPY  (live may have grown since the dump)"

# The restored audit chain must still verify: same code, pointed at the copy.
$COMPOSE run --rm --no-deps -T \
  -e DATABASE_URL="postgres://$POSTGRES_USER:$POSTGRES_PASSWORD@postgres:5432/$SCRATCH" \
  migrate python manage.py verify_audit

echo "$(date -u +%FT%TZ) restore check ok: $FILE"
