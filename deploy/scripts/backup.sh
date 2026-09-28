#!/usr/bin/env bash
# Nightly logical backup: pg_dump in custom format, kept for 7 days.
#   deploy/scripts/backup.sh
# The roadmap replaces this with continuous WAL archiving (point-in-time recovery).
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

DIR="${BACKUP_DIR:-/var/backups/grs}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ -f docker-compose.prod.yml ] && [ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.prod" ] \
  || COMPOSE="docker compose"

mkdir -p "$DIR"
FILE="$DIR/grs-$(date -u +%Y%m%dT%H%M%SZ).dump"
$COMPOSE exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 6 > "$FILE.part"
mv "$FILE.part" "$FILE"   # a half-written dump never looks like a good one
find "$DIR" -name 'grs-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
