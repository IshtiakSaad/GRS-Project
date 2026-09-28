# 2. Notifications go through an outbox table

**Status:** accepted

## Context

When a request changes, the citizen gets an SMS. Sending straight from the web request means a slow SMS gateway slows the API, and a crash between the database commit and the send loses the message. Putting a task on Redis after the commit has the same gap: if Redis is down at that moment, the message is gone.

## Decision

A notification is a row written in the same transaction as the change it announces. After commit, the row's id is handed to Celery as a fast path. A worker leases the row (a token and an expiry), sends it outside any transaction, and records the result; only the lease holder can complete it. A sweeper every 30 seconds re-enqueues rows the broker lost and recovers leases of crashed workers. Retries back off with jitter and stop at a cap. Status texts expire after 72 hours; action-required ones never do.

The chaos run showed a second gap: with the broker down, each web request still waited for it to time out. A per-process circuit breaker now skips the broker for 30 seconds after a failure and leaves the work to the sweeper.

## Consequences

- If the transaction rolls back, nothing is sent. If it commits, the message will be delivered, even across a broker outage (measured: 401 of 401).
- A message can be sent twice in rare crash windows. SMS texts are written so a duplicate is harmless.
- One more table to keep small: it is partitioned by month and old months are dropped.
