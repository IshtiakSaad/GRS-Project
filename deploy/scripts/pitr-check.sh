#!/usr/bin/env bash
# Prove point-in-time recovery works, from the off-host archive alone:
#   1. mark a named point in the live database's history (a restore point), counting rows just
#      before and just after it;
#   2. in a throwaway container with an empty disk, fetch the latest base backup from the
#      bucket and replay archived WAL up to exactly that point;
#   3. check the copy's row counts fall between the two counts, and its audit chain verifies
#      against the off-host anchors; report how long the restore took.
#   deploy/scripts/pitr-check.sh
# Nothing here touches the live database beyond reading it. An untested backup is a hope.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.prod" ] || COMPOSE="docker compose"
PROJECT=$($COMPOSE config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
SCRATCH=grs-pitr-check
PSQL="$COMPOSE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -qtA"
COUNTS="SELECT (SELECT count(*) FROM service_request), (SELECT count(*) FROM audit_log), (SELECT count(*) FROM app_user)"

# The same off-host settings the database archives with (docker-compose.yml, x-offsite-env).
OFFSITE_S3_BUCKET="${OFFSITE_S3_BUCKET:-offsite}"
OFFSITE_S3_ENDPOINT="${OFFSITE_S3_ENDPOINT-http://storage:8333}"
OFFSITE_S3_REGION="${OFFSITE_S3_REGION:-us-east-1}"
OFFSITE_S3_ACCESS_KEY="${OFFSITE_S3_ACCESS_KEY-grs-local}"
OFFSITE_S3_SECRET_KEY="${OFFSITE_S3_SECRET_KEY-grs-local-secret}"

cleanup() { docker rm -f "$SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

# 1. The point to restore to, bracketed by counts.
SYSID=$($PSQL -c "SELECT system_identifier FROM pg_control_system()")
POINT="pitr_check_$(date -u +%Y%m%dT%H%M%SZ)"
BEFORE=$($PSQL -F' ' -c "$COUNTS")
LSN=$($PSQL -c "SELECT pg_create_restore_point('$POINT')")
AFTER=$($PSQL -F' ' -c "$COUNTS")
SEGMENT=$($PSQL -c "SELECT pg_walfile_name('$LSN')")
$PSQL -c "SELECT pg_switch_wal()" >/dev/null
echo "restore point $POINT at $LSN (segment $SEGMENT); rows before=[$BEFORE] after=[$AFTER]"

for _ in $(seq 1 60); do  # wait until that segment has left the host
  ARCHIVED=$($PSQL -c "SELECT coalesce(last_archived_wal, '') FROM pg_stat_archiver")
  [[ "$ARCHIVED" > "$SEGMENT" || "$ARCHIVED" == "$SEGMENT" ]] && break
  sleep 2
done
[[ "$ARCHIVED" > "$SEGMENT" || "$ARCHIVED" == "$SEGMENT" ]] \
  || { echo "!! segment $SEGMENT was not archived within 2 minutes (last: $ARCHIVED)" >&2; exit 1; }

# 2. Restore into an empty container: base backup and WAL come only from the bucket.
STARTED=$(date +%s)
docker run -d --name "$SCRATCH" --network "${PROJECT}_default" \
  -e PGDATA=/var/lib/postgresql/data -e WALG_SYSTEM_ID="$SYSID" -e POSTGRES_USER="$POSTGRES_USER" \
  -e OFFSITE_S3_BUCKET="$OFFSITE_S3_BUCKET" -e OFFSITE_S3_ENDPOINT="$OFFSITE_S3_ENDPOINT" \
  -e OFFSITE_S3_REGION="$OFFSITE_S3_REGION" -e OFFSITE_S3_ACCESS_KEY="$OFFSITE_S3_ACCESS_KEY" \
  -e OFFSITE_S3_SECRET_KEY="$OFFSITE_S3_SECRET_KEY" \
  -v "$PWD/deploy/postgres:/grs:ro" -v "$PWD/deploy/postgres/conf.d:/etc/postgresql/conf.d:ro" \
  grs-postgres:17 bash -c '
    set -e
    mkdir -p "$PGDATA" && chown postgres:postgres "$PGDATA" && chmod 700 "$PGDATA"
    gosu postgres bash /grs/wal-g.sh backup-fetch "$PGDATA" LATEST
    gosu postgres touch "$PGDATA/recovery.signal"
    exec gosu postgres postgres \
      -c restore_command="bash /grs/wal-g.sh wal-fetch %f %p" \
      -c recovery_target_name='"$POINT"' -c recovery_target_action=promote \
      -c archive_mode=off' >/dev/null

in_copy() { docker exec "$SCRATCH" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qtA "$@"; }
for _ in $(seq 1 150); do
  [ "$(in_copy -c 'SELECT pg_is_in_recovery()' 2>/dev/null)" = "f" ] && break
  if [ "$(docker inspect -f '{{.State.Running}}' "$SCRATCH")" != "true" ]; then
    docker logs --tail 40 "$SCRATCH" >&2; echo "!! the restore container stopped" >&2; exit 1
  fi
  sleep 2
done
[ "$(in_copy -c 'SELECT pg_is_in_recovery()')" = "f" ] \
  || { docker logs --tail 40 "$SCRATCH" >&2; echo "!! recovery did not finish in 5 minutes" >&2; exit 1; }
TOOK=$(( $(date +%s) - STARTED ))

# 3. The copy stopped exactly at the point: between the counts taken either side of it.
RESTORED=$(in_copy -F' ' -c "$COUNTS")
echo "restored rows=[$RESTORED] in ${TOOK}s"
read -r -a b <<< "$BEFORE"; read -r -a a <<< "$AFTER"; read -r -a r <<< "$RESTORED"
for i in 0 1 2; do
  if (( r[i] < b[i] || r[i] > a[i] )); then
    echo "!! restored count ${r[i]} outside [${b[i]}, ${a[i]}] (requests/audit rows/users)" >&2
    exit 1
  fi
done

$COMPOSE run --rm --no-deps -T \
  -e DATABASE_URL="postgres://$POSTGRES_USER:$POSTGRES_PASSWORD@$SCRATCH:5432/$POSTGRES_DB" \
  migrate python manage.py verify_audit --restored-copy

echo "$(date -u +%FT%TZ) pitr check ok: restored to $POINT from the off-host archive in ${TOOK}s"
