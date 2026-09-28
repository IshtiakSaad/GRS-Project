# 4. Two Redis instances, split by how they may fail

**Status:** accepted

## Context

Redis serves two jobs here with opposite needs. The task queue must never drop a task under memory pressure. Rate-limit counters and cache entries are disposable: losing them is harmless. One instance cannot be configured for both: `noeviction` makes the cache fill up and refuse writes; an eviction policy lets the queue silently lose tasks.

## Decision

- `redis-broker`: `noeviction`, no persistence. A full broker refuses new tasks, which the application treats like an outage (the outbox keeps the work).
- `redis-cache`: `allkeys-lru`, no persistence. The rate limiter fails open if it is unreachable, so a cache outage never blocks citizens.

## Consequences

- Each instance is configured for its own failure mode, and each can be restarted without touching the other.
- One more container to run. On one server this costs a few megabytes.
- Neither holds anything PostgreSQL cannot rebuild, so neither needs backups.
