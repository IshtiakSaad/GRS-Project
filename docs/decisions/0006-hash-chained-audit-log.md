# 6. The audit log is append-only and hash-chained

**Status:** accepted

## Context

An audit log is only useful if nobody can quietly change it, including someone with database access. Grants and triggers stop the application's own roles, but a database owner can disable a trigger, and a restored backup could be edited before restore.

## Decision

Log tables accept inserts only (trigger plus grants). Once a minute a single sealer (a PostgreSQL advisory lock keeps it single) gives each new row the next sequence number and `SHA-256(previous hash + the row's canonical content)`. Each batch writes a checkpoint (anchor) that is copied, locked, to a write-once bucket on another system (S3 Object Lock). The server's credentials can add objects there but not delete versions or lift a lock. `manage.py verify_audit` walks the whole chain and checks it against every version of every off-host anchor, not only the database's own anchor table; the nightly restore checks run it on the restored copies.

## Alternatives considered

- **Trust grants and triggers alone.** They stop the application; they do not stop the database owner, a restored backup edited on the way in, or root on the server.
- **Sign each row with a key on the server.** Whoever has root has the key, and can re-sign whatever they change.
- **Send the log to a hosted logging service.** Moves the trust to a third party and sends citizens' request details out of the office's control. Only the checkpoints leave the server, and a checkpoint is a hash: it reveals nothing.
- **A blockchain.** Distributed consensus solves a problem this system does not have. A chain of hashes and a write-once copy give the same property with none of the machinery.

## Consequences

- Changing, deleting or inserting any sealed row breaks the chain from that row on. Re-hashing the rest of the chain to hide it still disagrees with the stored anchors. Tests do each of these as the table owner and expect the check to fail.
- Rows are unsealed for up to a minute.
- Someone with root on the server can rewrite the rows, re-hash the chain and fix the database's anchor table, and the chain looks whole from inside. The locked copies still hold the old hashes, so the check fails. Overwriting a copy only adds a version; the locked original stays and disagrees. Cutting rows off the end fails too: the copies go further than the chain. Tests do each of these.
- If the store is unreachable, verification fails rather than passing on the database's word alone, and anchors wait in the database until it is back (the monitor alerts after 10 minutes).
- The demo locks anchors for days in GOVERNANCE mode so the account can be closed; a real deployment would lock them for years in COMPLIANCE mode, which nobody can lift.

## What would change this

A real deployment would lock checkpoints for years in COMPLIANCE mode and could add an independent timestamp (RFC 3161) to each, so even the account holder could not backdate one.
