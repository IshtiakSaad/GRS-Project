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
# Mailpit holds the demo's email only where email is not relayed for real (locally).
MAIL=""; [ "${EMAIL_HOST:-mailpit}" = "mailpit" ] && MAIL=mailpit

# The administrator's two-step key survives the reset: reviewers are sent it once, with the
# submission. Read it still encrypted (only the app's key decrypts it); empty on a first run.
GRS_DEMO_ADMIN_KEY=$($COMPOSE exec -T -u postgres postgres psql -d "$POSTGRES_DB" -tAc \
  "SELECT totp_secret_encrypted FROM app_user WHERE phone = '+8801000000001'" 2>/dev/null || true)
export GRS_DEMO_ADMIN_KEY

$COMPOSE stop api api-auth worker beat postgres storage redis-broker redis-cache $MAIL
$COMPOSE rm -f postgres storage redis-broker redis-cache $MAIL
docker volume rm "${PROJECT}_pgdata" "${PROJECT}_storage"
$COMPOSE up -d --wait postgres storage redis-broker redis-cache $MAIL
$COMPOSE run --rm migrate
$COMPOSE run --rm --no-deps -e GRS_DEMO_ADMIN_KEY api python manage.py seed_demo
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
