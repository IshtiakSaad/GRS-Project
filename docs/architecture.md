# Architecture

One Django codebase, run as several processes with different jobs, around one PostgreSQL database. Everything runs from one Compose file on one server; each piece can move to its own host later without code changes.

```mermaid
flowchart LR
  phone([Citizen / officer / admin]) -->|HTTPS| nginx[Nginx<br/>TLS, buffering,<br/>per-address limits,<br/>web app files]
  nginx -->|password routes| auth[api-auth<br/>gunicorn pool]
  nginx -->|everything else| api[api<br/>gunicorn pool]
  phone -.->|signed upload / download| files[(Object storage<br/>SeaweedFS, S3 API)]
  nginx -. files.domain .-> files

  api --> pg[(PostgreSQL<br/>source of truth)]
  auth --> pg
  api --> cache[(redis-cache<br/>limits, cache<br/>may evict)]
  auth --> cache
  api -->|fast path| broker[(redis-broker<br/>task queue<br/>never evicts)]

  broker --> worker[worker<br/>Celery]
  beat[beat<br/>schedules] --> broker
  worker --> pg
  worker --> files
  worker --> sms[SMS provider]
  worker --> mail[SMTP]

  standby[(PostgreSQL standby<br/>optional)] -.->|streaming| pg
```

## Processes

| Process | Job | If it stops |
|---|---|---|
| `nginx` | TLS, buffers slow clients, per-address rate limits, routes password hashing to `api-auth`, serves the web app (static files built from `web/`) | Site down |
| `api` | Every endpoint except password hashing | Site down (Nginx answers 502) |
| `api-auth` | Login, register, password set/reset, two-step verify | Logins fail; logged-in users unaffected |
| `worker` | Sends notifications, verifies uploads, recomputes deadlines | Work waits in PostgreSQL; nothing is lost |
| `beat` | Triggers the sweepers, sealer, overdue check, cleanup | Same as above |
| `postgres` | All data and every rule that can be a constraint | Site down |
| `redis-broker` | Task queue | Web requests continue; sweepers deliver after restart |
| `redis-cache` | Rate-limit counters, cache | Limits fail open; everything else continues |
| `storage` | Citizens' files | Uploads and downloads fail; links can still be signed |

## How a submission flows

1. The citizen's app sends `POST /requests/{id}/actions/submit` with an `Idempotency-Key`. A retry with the same key returns the stored answer instead of a second request.
2. In **one transaction**: lock the request row, check the transition is allowed for this user and state, give it a tracking number from the year's sequence (with a check digit), compute its deadline in working days, write a timeline event, write an audit row, and write a notification row.
3. After commit, the notification is handed to the broker. If the broker is down, the row simply waits: the **sweeper** finds it within 30 seconds of the broker coming back. A circuit breaker stops each web process from trying the dead broker again for 30 seconds, so requests stay fast during an outage.
4. A worker **leases** the notification row, sends the SMS or email outside any transaction, and records the result. Only the lease holder can complete it; a crashed worker's lease expires and the row is retried, with a cap on attempts.

## The rules live in the database

The application checks everything first, but PostgreSQL is the last line:

- Status and the columns each status requires (a resolved request has a resolution note, an assigned one has an officer).
- One open SLA pause per request; valid deadlines; a reviewer is never the person being reviewed.
- Audit, timeline and access-log tables accept inserts only (a trigger plus grants). The one allowed update to an audit row is sealing it, once.
- The API connects as a role that cannot change the schema; migrations run as another; the worker has a third role with only what it needs. Each role has its own statement timeout.

Tests insert illegal rows directly and assert that PostgreSQL rejects them (`tests/integration/db/`).

## Deadlines

A category has a target in working days. Deadlines count Sunday to Thursday in Dhaka time, skip holidays and suspension periods, and stop while the office waits on the citizen. Changing a holiday recomputes the open requests it affects, in batches that lock the same rows a transition would. Every five minutes, requests past their deadline are flagged once per cycle and the officer and department admins are told.

## Accountability

- **Audit log**: every state change and admin action, append-only. Every minute a sealer chains new rows with SHA-256 and stores a checkpoint in object storage. `manage.py verify_audit` walks the chain; the nightly restore check runs it on the restored copy.
- **Access log**: every time staff open, change or download a request, and every list page they see. Citizens see which office and role looked (not names); admins see who.
- **Break-glass**: opening a request outside one's department needs a reason code, and appears in a report.
- **Review queue**: rejections near the deadline, and a sample of resolutions, go to an administrator who can uphold or overturn them.

## Scaling path

Measured ceiling on 2 vCPUs: about 80 requests a second with no errors. The next steps, in order:

1. More `api` replicas behind the same Nginx (stateless; sessions are tokens).
2. PostgreSQL on its own host, with the standby as a read replica for statistics.
3. Broker and cache on their own hosts.
4. Object storage replicated across two hosts.

Nothing in the code assumes a single host.
