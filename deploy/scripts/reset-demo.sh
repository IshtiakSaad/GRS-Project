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

$COMPOSE stop api api-auth worker beat postgres storage redis-broker redis-cache mailpit
$COMPOSE rm -f postgres storage redis-broker redis-cache mailpit
docker volume rm "${PROJECT}_pgdata" "${PROJECT}_storage"
$COMPOSE up -d --wait postgres storage redis-broker redis-cache mailpit
$COMPOSE run --rm migrate
$COMPOSE run --rm --no-deps api python manage.py seed_demo
$COMPOSE up -d --wait   # report ok only once every service is healthy
$COMPOSE restart nginx  # drop the old containers' addresses now, not after a few failed requests
echo "$(date -u +%FT%TZ) demo reset ok"
