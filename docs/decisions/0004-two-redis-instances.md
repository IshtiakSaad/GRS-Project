# 4. Two Redis instances, split by how they may fail

**Status:** accepted

## Context

Redis serves two jobs here with opposite needs. The task queue must never drop a task under memory pressure. Rate-limit counters and cache entries are disposable: losing them is harmless. One instance cannot be configured for both: `noeviction` makes the cache fill up and refuse writes; an eviction policy lets the queue silently lose tasks.

## Decision

- `redis-broker`: `noeviction`, no persistence. A full broker refuses new tasks, which the application treats like an outage (the outbox keeps the work).
- `redis-cache`: `allkeys-lru`, no persistence. The rate limiter fails open if it is unreachable, so a cache outage never blocks citizens.

## Alternatives considered

- **One Redis, with expiring keys for the cache and `volatile-lru`.** Works until one cache key is written without a TTL, and then the cache can grow until the queue cannot write.
- **RabbitMQ as the broker.** Durable queues and acknowledgements, and a different service to learn, configure and watch. The outbox already makes the queue's durability unnecessary (decision 2).
- **PostgreSQL as the queue.** It already holds the outbox, and could hold the tasks too. Celery on Redis is a well-trodden path, and it keeps high-frequency polling off the database at the 9 a.m. peak.

## Consequences

- Each instance is configured for its own failure mode, and each can be restarted without touching the other.
- One more container to run. On one server this costs a few megabytes.
- Neither holds anything PostgreSQL cannot rebuild, so neither needs backups.

## What would change this

A need for tasks that must survive a broker restart without an outbox row behind them. Today every task that matters has one.
