#!/usr/bin/env bash
# Write the server's .env with fresh random secrets. Run once, on the server:
#   OFFSITE_S3_BUCKET=my-locked-bucket OFFSITE_S3_REGION=ap-south-1 \
#     deploy/scripts/gen-env.sh demo.example.org you@example.org
# The file never leaves the server and is never committed. Refuses to overwrite.
set -euo pipefail
cd "$(dirname "$0")/../.."

DOMAIN="${1:?usage: gen-env.sh <domain> <letsencrypt-email>}"
EMAIL="${2:?usage: gen-env.sh <domain> <letsencrypt-email>}"
[ -e .env ] && { echo ".env exists; not overwriting" >&2; exit 1; }

rand() { openssl rand -hex "${1:-24}"; }
fernet() { openssl rand -base64 32 | tr '+/' '-_'; }

OWNER=$(rand) API=$(rand) WORKER=$(rand) REPL=$(rand)
umask 077
cat > .env <<ENV
GRS_DOMAIN=$DOMAIN
LETSENCRYPT_EMAIL=$EMAIL
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=$(rand 32)
# 127.0.0.1: the containers' own health checks call the app directly.
DJANGO_ALLOWED_HOSTS=$DOMAIN,127.0.0.1,localhost

POSTGRES_DB=grs
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$(rand)
GRS_OWNER_PASSWORD=$OWNER
GRS_API_PASSWORD=$API
GRS_WORKER_PASSWORD=$WORKER
GRS_REPLICATOR_PASSWORD=$REPL
OWNER_DATABASE_URL=postgres://grs_owner:$OWNER@postgres:5432/grs
API_DATABASE_URL=postgres://grs_api:$API@postgres:5432/grs
WORKER_DATABASE_URL=postgres://grs_worker:$WORKER@postgres:5432/grs

REDIS_BROKER_URL=redis://redis-broker:6379/0
REDIS_CACHE_URL=redis://redis-cache:6379/0

S3_ACCESS_KEY=grs-$(rand 8)
S3_SECRET_KEY=$(rand)
S3_BUCKET=attachments
# Off-host store (audit anchors, WAL archive, base backups): an S3 bucket with Object Lock on
# another system. Empty endpoint and keys: AWS, with the instance role's credentials.
OFFSITE_S3_BUCKET=${OFFSITE_S3_BUCKET:?set OFFSITE_S3_BUCKET (the Object Lock bucket)}
OFFSITE_S3_REGION=${OFFSITE_S3_REGION:?set OFFSITE_S3_REGION}
OFFSITE_S3_ENDPOINT=
OFFSITE_S3_ACCESS_KEY=
OFFSITE_S3_SECRET_KEY=
OFFSITE_LOCK_DAYS=7
S3_ENDPOINT=http://storage:8333
S3_PUBLIC_ENDPOINT=https://files.$DOMAIN

JWT_SIGNING_KEYS=k1=$(rand 32)
JWT_ACTIVE_KID=k1
FIELD_ENCRYPTION_KEYS=$(fernet)
# Public demo: only +880 10 numbers, fake SMS inbox, nightly reset. Synthetic data only.
DEMO_MODE=true

GUNICORN_WORKERS=3
LOG_LEVEL=INFO
ENV
echo "wrote .env for $DOMAIN (mode 600). Next: deploy/scripts/init-tls.sh"
