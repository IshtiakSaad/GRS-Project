#!/bin/bash
# PostgreSQL's archive_command: ship one finished WAL segment off the host. A non-zero exit makes
# PostgreSQL keep the segment and retry, so nothing is skipped while the store is unreachable
# (the monitor alerts on it). WAL_ARCHIVE=off reports success without shipping: for machines
# that should not archive at all, never for one that has backups.
[ "${WAL_ARCHIVE:-on}" = "on" ] || exit 0
exec bash /grs/wal-g.sh wal-push "$1"
