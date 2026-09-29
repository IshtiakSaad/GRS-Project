#!/bin/bash
# WAL-G against the off-host bucket, under wal/<this cluster's system identifier>/. A cluster
# created from scratch (the demo's nightly reset) gets a new identifier, so two databases never
# share an archive.
#   bash /grs/wal-g.sh wal-push <file>   archive_command (wal-archive.sh)
#   bash /grs/wal-g.sh backup-push       nightly base backup (deploy/scripts/backup.sh)
#   bash /grs/wal-g.sh backup-list
# A restore into an empty directory has no identifier yet: pass it in WALG_SYSTEM_ID.
# Credentials: OFFSITE_S3_ACCESS_KEY if set (local), else the server's instance role.
set -euo pipefail

SYSID="${WALG_SYSTEM_ID:-$(pg_controldata "$PGDATA" | awk -F': *' '/Database system identifier/ {print $2}')}"
export WALG_S3_PREFIX="s3://${OFFSITE_S3_BUCKET:?}/wal/$SYSID"
export AWS_REGION="${OFFSITE_S3_REGION:-us-east-1}"
if [ -n "${OFFSITE_S3_ENDPOINT:-}" ]; then
  export AWS_ENDPOINT="$OFFSITE_S3_ENDPOINT" AWS_S3_FORCE_PATH_STYLE=true
fi
if [ -n "${OFFSITE_S3_ACCESS_KEY:-}" ]; then
  export AWS_ACCESS_KEY_ID="$OFFSITE_S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$OFFSITE_S3_SECRET_KEY"
fi
export WALG_COMPRESSION_METHOD=zstd
export PGHOST=/var/run/postgresql PGUSER="${POSTGRES_USER:-postgres}" PGDATABASE=postgres
exec wal-g "$@"
