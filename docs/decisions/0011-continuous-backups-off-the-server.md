# 11. Backups are continuous and leave the server

**Status:** accepted

## Context

A nightly `pg_dump` on the same disk loses up to a day of citizens' requests, and loses everything with the disk. The target is at most about a minute of committed data lost (RPO) and an hour to recover (RTO). A backup that has never been restored is not known to work.

## Decision

PostgreSQL archives every finished WAL segment to the off-host bucket with WAL-G, and closes a segment at least once a minute while anything is written (`archive_timeout = 60`). A nightly base backup goes to the same bucket; the last seven are kept. The archive for each database lives under its system identifier, so the demo's nightly rebuild starts a new folder instead of mixing two histories.

Every night, and in CI on every push, `deploy/scripts/pitr-check.sh` proves it: it marks a named restore point in the live database, restores into an empty container from the bucket alone to exactly that point, checks the row counts fall between the counts taken either side of it, and verifies the audit chain in the copy. The nightly `pg_dump` stays as a second, independent kind of backup.

The server reaches the bucket through its instance role, so no key is stored on it, and the role cannot delete object versions: a compromised server can add to its backups but not destroy them.

## Alternatives considered

- **Nightly `pg_dump` only.** Simple and portable, and up to a day of citizens' requests lost with the disk.
- **A streaming standby only.** Minimal data loss when the disk dies, and no protection at all against a mistake: a wrong `DELETE` reaches the standby in milliseconds. The standby stays as an option; it is not a backup.
- **pgBackRest instead of WAL-G.** Equally capable. WAL-G is a single binary that speaks S3 directly, which fits an image that should stay small.
- **A managed database with point-in-time recovery.** The same guarantee bought instead of built, and the end of running the stack anywhere Docker runs (decision 8).

## Consequences

- Data at risk from losing the server: about a minute. Recovery: fetch the latest base backup and replay WAL, measured by the drill each night.
- If the bucket is unreachable, PostgreSQL keeps the unarchived segments and retries; nothing is skipped, but the disk fills if the outage lasts for days. The monitor alerts.
- An idle minute with any write still ships a 16 MB segment (compressed to a few KB): at most 1,440 small uploads a day.

## What would change this

A requirement to lose no committed data at all. That needs a synchronous replica on another host, which costs latency on every write; about a minute is the right trade for this system.
