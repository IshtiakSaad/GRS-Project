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

## Results on the live server (28 Sep 2026)

AWS `m7i-flex.large` (2 vCPU, 8 GB), Mumbai. k6 ran on the same machine, sharing its two CPUs with the application, so these numbers are conservative.

**Storm.** The full storm is about twice what this machine can serve. It degraded by slowing down, not by failing:

| Load | Throughput | Browse p50 / p95 | Submit p50 / p95 | Login p50 / p95 | Errors |
|---|---|---|---|---|---|
| Full storm (`SCALE=1`) | 86 req/s (saturated; k6 dropped 3,214 planned iterations) | 2.9 s / 8.0 s | 3.0 s / 8.5 s | 7.6 s / 11.1 s | **0 of 9,763** |
| Half storm (`SCALE=0.5`) | 72 req/s | 15 ms / 0.86 s | 41 ms / 0.96 s | 58 ms / 1.47 s | **0 of 7,775** |

Capacity is about 70–85 requests a second on two vCPUs. The design scales out rather than up: more `api` replicas behind the same Nginx and a larger database host (see the architecture notes).

**Broker outage** (30 s, 4 submissions/s):

| | Result |
|---|---|
| Submit p95 while the broker was down | **32 ms** (worst 62 ms) |
| Failed submissions | **0 of 401** |
| Notifications delivered after restart | **401 of 401**, within 30 s |

**Edge limit** (from Dhaka over the internet, 60 logins/s from one address for 10 s): 138 reached the application (10/s plus the burst of 40) and 462 were refused at Nginx with the API's JSON `RATE_LIMITED` body and `Retry-After`.

**Backup and restore.** A backup taken right after the load tests restored with identical counts (1,219 requests, 4,887 audit rows, 909 users), and the restored audit chain verified all 4,887 rows.
