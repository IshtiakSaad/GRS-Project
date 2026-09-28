#!/usr/bin/env bash
# Get the first certificate, before Nginx exists to answer the challenge. Run once:
#   deploy/scripts/init-tls.sh            # Let's Encrypt staging first (no rate limits)
#   deploy/scripts/init-tls.sh --live     # then the real certificate
# Renewals afterwards are the certbot service's job (docker-compose.prod.yml).
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

STAGING="--staging"
[ "${1:-}" = "--live" ] && STAGING="--force-renewal"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$COMPOSE stop nginx 2>/dev/null || true   # free port 80 for the standalone challenge

$COMPOSE run --rm --no-deps -p 80:80 --entrypoint certbot certbot certonly \
  --standalone $STAGING --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL" \
  --cert-name "$GRS_DOMAIN" \
  -d "$GRS_DOMAIN" -d "files.$GRS_DOMAIN" -d "mail.$GRS_DOMAIN"

echo "certificate ready for $GRS_DOMAIN. Next: deploy/scripts/deploy.sh"
