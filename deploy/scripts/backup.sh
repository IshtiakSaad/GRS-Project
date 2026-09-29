#!/usr/bin/env bash
# Nightly backups, two independent kinds:
# - a base backup to the off-host bucket (WAL-G). With the WAL that PostgreSQL archives there
#   continuously, it restores the database to any moment since (point-in-time recovery). The
#   last 7 are kept; older ones and their WAL are pruned.
# - a logical pg_dump on this server, kept 7 days: quick to restore one table or inspect, and
#   independent of WAL-G.
#   deploy/scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

DIR="${BACKUP_DIR:-/var/backups/grs}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ -f docker-compose.prod.yml ] && [ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.prod" ] \
  || COMPOSE="docker compose"

$COMPOSE exec -T -u postgres postgres bash /grs/wal-g.sh backup-push
$COMPOSE exec -T -u postgres postgres bash /grs/wal-g.sh delete retain FULL 7 --confirm
echo "$(date -u +%FT%TZ) base backup ok (off-host)"

mkdir -p "$DIR"
FILE="$DIR/grs-$(date -u +%Y%m%dT%H%M%SZ).dump"
$COMPOSE exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 6 > "$FILE.part"
mv "$FILE.part" "$FILE"   # a half-written dump never looks like a good one
find "$DIR" -name 'grs-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
