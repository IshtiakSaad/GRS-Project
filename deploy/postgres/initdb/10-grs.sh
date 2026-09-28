#!/bin/bash
# Runs once, when the postgres container initialises an empty data directory.
set -euo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$GRS_OWNER_PASSWORD" \
  -v api_pw="$GRS_API_PASSWORD" \
  -v worker_pw="$GRS_WORKER_PASSWORD" \
  -v replicator_pw="$GRS_REPLICATOR_PASSWORD" \
  -v db="$POSTGRES_DB" \
  -v bootstrap_user="$POSTGRES_USER" \
  -f /grs/roles.sql

# The standby streams WAL as grs_replicator; replication connections need their own rule.
echo "host replication grs_replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"

if [ "${GRS_DEV_CREATEDB:-0}" = "1" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /grs/dev.sql
fi
