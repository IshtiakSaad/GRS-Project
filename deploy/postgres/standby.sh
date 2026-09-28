#!/bin/bash
# Warm standby: a read-only copy that streams every change from the primary.
# First start clones the primary with pg_basebackup; later starts just resume streaming.
# Promotion to primary is a manual, audited decision (docs/runbook.md), never automatic.
set -euo pipefail

SLOT=standby_1

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"

  until gosu postgres pg_isready -h postgres -p 5432 -q; do
    echo "standby: waiting for primary"
    sleep 2
  done

  export PGPASSWORD="$GRS_REPLICATOR_PASSWORD"
  # The slot makes the primary keep WAL the standby has not received yet (capped by
  # max_slot_wal_keep_size). Reuse it if a previous clone already created it.
  if ! gosu postgres pg_basebackup -h postgres -U grs_replicator -D "$PGDATA" \
       -X stream -R -C -S "$SLOT" --checkpoint=fast; then
    rm -rf "${PGDATA:?}"/*
    gosu postgres pg_basebackup -h postgres -U grs_replicator -D "$PGDATA" \
      -X stream -R -S "$SLOT" --checkpoint=fast
  fi
  unset PGPASSWORD
fi

exec gosu postgres postgres
