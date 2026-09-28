# Load and chaos tests

Three [k6](https://k6.io) scripts, each run from a container on the stack's own network.

| Script | Question it answers |
|---|---|
| `storm.js` | Can the service hold a 9 am rush: a login burst, citizens browsing, requests being filed? |
| `chaos.sh` + `chaos.js` | If the task broker dies mid-rush, do submissions still succeed, and is every notification still delivered? |
| `edge-check.js` | Does Nginx cut one address hammering the login route, with the API's JSON error? |

## Setup (demo mode only)

```bash
docker compose run --rm --no-deps api python manage.py seed_demo
docker compose run --rm --no-deps api python manage.py seed_load_users 900
```

`seed_load_users` creates synthetic citizens on the unassigned `+880 1099…` range. Each virtual user logs in as a different citizen, so per-phone and per-user limits apply as they would to real people. `storm.js` calls the app containers directly (`api`, `api-auth`) so it measures the application, not the per-address edge limit that one load generator would hit. `edge-check.js` measures that limit separately.

## Run

```bash
NET=$(basename "$PWD")_default   # the Compose network
docker run --rm --network $NET -e HOST=$GRS_DOMAIN -v "$PWD/loadtest:/scripts" \
  grafana/k6:1.3.0 run --summary-export=/scripts/results/storm.json /scripts/storm.js

# broker outage; use a fresh slice of accounts so earlier runs' submit limits don't interfere
USER_OFFSET=300 COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml" loadtest/chaos.sh

docker run --rm --network $NET -e BASE_URL=https://nginx -e HOST=$GRS_DOMAIN -e INSECURE=1 \
  -v "$PWD/loadtest:/scripts" grafana/k6:1.3.0 run /scripts/edge-check.js
```

## What the storm does

| Scenario | Load | Pass mark |
|---|---|---|
| `login_burst` | ramps to 30 logins/s, holds 1 min (Argon2id on the `api-auth` pool) | p95 < 2 s |
| `browse` | 60 iterations/s: list my requests, open one | p95 < 500 ms, < 1% errors |
| `submit` | 5 new requests/s: draft, then submit with an `Idempotency-Key` | p95 < 1 s, < 1% errors |

## What the chaos run found, and the fix

The first run stopped `redis-broker` for 30 s under steady submissions. No notification was lost: the outbox rows waited in PostgreSQL and the sweeper delivered all of them after the restart. But submissions slowed badly (p95 11.7 s, worst 20 s). Each enqueue waited about 4 s for the dead broker (Celery's default connection timeout), a submission enqueues several messages, and sync workers queued behind each other.

Fix (`apps/common/broker.py`): a per-process circuit breaker. After one failed enqueue, a process stops trying for 30 s and leaves the work to the sweepers, which already cover it. The connection timeout is now 1 s.

Rerun, same outage, on a laptop rehearsal of the production stack:

| While the broker was down | Before | After |
|---|---|---|
| Submit p95 | 11.7 s | **99 ms** |
| Worst request | 20 s | 4 s (the first probe per worker) |
| Failed submissions | – | **0 of 401** |
| Notifications delivered after restart | all | **401 of 401**, within 65 s |

The results from the live server are in the main README.
