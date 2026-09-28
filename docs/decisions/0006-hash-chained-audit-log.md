# 6. The audit log is append-only and hash-chained

**Status:** accepted

## Context

An audit log is only useful if nobody can quietly change it, including someone with database access. Grants and triggers stop the application's own roles, but a database owner can disable a trigger, and a restored backup could be edited before restore.

## Decision

Log tables accept inserts only (trigger plus grants). Once a minute a single sealer (a PostgreSQL advisory lock keeps it single) gives each new row the next sequence number and `SHA-256(previous hash + the row's canonical content)`. Each batch writes a checkpoint (anchor) that is also copied to object storage. `manage.py verify_audit` walks the whole chain and checks every anchor; the nightly restore check runs it on the restored copy.

## Consequences

- Changing, deleting or inserting any sealed row breaks the chain from that row on. Re-hashing the rest of the chain to hide it still disagrees with the stored anchors. Tests do each of these as the table owner and expect the check to fail.
- Rows are unsealed for up to a minute.
- Today the anchors sit on the same host. Real tamper evidence needs them on a separate, write-once bucket (roadmap).
