#!/usr/bin/env bash
# Deploy the latest main, or a given ref, and roll back if the new build is not healthy:
#   deploy/scripts/deploy.sh            # origin/main
#   deploy/scripts/deploy.sh v1.0.0     # a tag or commit
# Migrations run first (the migrate service); every app service then waits for them.
# Rollback moves the code back; it cannot undo a migration, so migrations stay additive.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
REF="${1:-origin/main}"
PREVIOUS=$(git rev-parse --short HEAD)

release() {
  git checkout -q --detach "$1"
  export BUILD_SHA
  BUILD_SHA=$(git rev-parse --short HEAD)
  echo "== building $BUILD_SHA"
  $COMPOSE build -q
  $COMPOSE up -d --remove-orphans
}

healthy() {
  # Readiness through Nginx and TLS, and it must be the build we just started.
  for _ in $(seq 1 30); do
    body=$(curl -fsS --max-time 3 "https://$GRS_DOMAIN/health/ready" 2>/dev/null || true)
    if echo "$body" | grep -q "\"build\": *\"$BUILD_SHA\""; then
      return 0
    fi
    sleep 4
  done
  return 1
}

git fetch -q --tags origin
release "$REF"
if healthy; then
  echo "== live: $BUILD_SHA"
  exit 0
fi

echo "!! $BUILD_SHA is not healthy; rolling back to $PREVIOUS" >&2
$COMPOSE logs --tail 50 api >&2 || true
release "$PREVIOUS"
healthy && echo "== rolled back to $PREVIOUS" >&2 || echo "!! rollback also unhealthy" >&2
exit 1
