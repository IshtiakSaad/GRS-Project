# Government Service Request Management System

A backend for citizens to file service requests with government offices, for officers to work them, and for administrators to oversee them.

Built with Python, Django REST Framework, PostgreSQL, JWT auth and Docker Compose.

Status: work in progress.

## Run it locally

Needs Docker with Compose v2. No cloud accounts.

```bash
cp .env.example .env
docker compose up -d --build --wait
```

| What | Where |
|---|---|
| API docs (Swagger UI) | http://localhost:8080/api/docs/ |
| Readiness | http://localhost:8080/health/ready |
| Outgoing email (Mailpit) | http://localhost:8025 |

Run the tests against the running stack:

```bash
docker build --target test -t grs-app:test .
docker run --rm --network grs-project_default \
  -e DATABASE_URL=postgres://grs_owner:owner-local@postgres:5432/grs \
  -e REDIS_CACHE_URL=redis://redis-cache:6379/1 \
  -e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
  grs-app:test
```

## Services

| Service | Why it is here |
|---|---|
| `postgres` | The only source of truth. Every rule that can be a database constraint is one |
| `api` | The REST API (Django + DRF under gunicorn) |
| `api-auth` | Same code, separate worker pool for password hashing, so a login rush cannot starve the rest of the API |
| `nginx` | Buffers slow mobile clients, routes the password-hashing endpoints to `api-auth`, enforces timeouts |
| `worker`, `beat` | Background work: notifications, file checks, deadline tracking |
| `redis-broker` | Task queue. Never evicts; holds nothing that PostgreSQL cannot rebuild |
| `redis-cache` | Cache and rate-limit counters. May evict anything; the API keeps working if it is down |
| `storage` | S3-compatible file storage (SeaweedFS), self-hosted so citizens' files stay in-country |
| `mailpit` | Catches outgoing email locally |
