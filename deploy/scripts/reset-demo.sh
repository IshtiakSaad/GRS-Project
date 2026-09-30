#!/usr/bin/env bash
# Nightly reset of the public demo: throw away the database, stored files, queues and demo
# email, then migrate and reseed. Visitors' changes last at most a day.
#   deploy/scripts/reset-demo.sh
# Refuses to run unless DEMO_MODE is on: this deletes everything.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
[ "${DEMO_MODE:-false}" = "true" ] || { echo "DEMO_MODE is off; refusing to reset" >&2; exit 1; }

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
[ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.prod" ] || COMPOSE="docker compose"
PROJECT=$($COMPOSE config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')

# Whatever fails below, the site must not stay down: bring every service back on the way out.
trap '$COMPOSE up -d >/dev/null 2>&1 || true' EXIT

$COMPOSE stop api api-auth worker beat postgres storage redis-broker redis-cache mailpit
$COMPOSE rm -f postgres storage redis-broker redis-cache mailpit
docker volume rm "${PROJECT}_pgdata" "${PROJECT}_storage"
$COMPOSE up -d --wait postgres storage redis-broker redis-cache mailpit
$COMPOSE run --rm migrate
$COMPOSE run --rm --no-deps api python manage.py seed_demo
# Every service, including offsite-init, which recreates the off-host bucket if the wipe took
# it (where it is a stand-in on this server's storage). Report ok only once all are healthy.
$COMPOSE up -d --wait
$COMPOSE restart nginx  # drop the old containers' addresses now, not after a few failed requests
# A new cluster archives under a new folder; give it a base backup now, not at the next night.
# The site is already up: a failed backup is reported (and the monitor alerts), not fatal.
if ! $COMPOSE exec -T -u postgres postgres bash /grs/wal-g.sh backup-push; then
  echo "$(date -u +%FT%TZ) demo reset ok, but the base backup failed" >&2
  exit 1
fi
echo "$(date -u +%FT%TZ) demo reset ok"
