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

Load the demo data (synthetic; every phone number is on the unassigned `010` prefix):

```bash
docker compose run --rm --no-deps api python manage.py seed_demo
```

It creates three offices, five services, officers, citizens and requests in every state, and prints the demo password and the administrator's two-step login secret. Codes that the system would send by SMS are readable at `GET /api/v1/demo/sms/{phone}`, only while `DEMO_MODE` is on.

A request's life, as a citizen and then an officer:

| Step | Call |
|---|---|
| Log in | `POST /api/v1/auth/login` with `{"phone": "01000000101", "password": "…"}` |
| Draft | `POST /api/v1/requests` with a `category` code from `GET /api/v1/categories` |
| Submit | `POST /api/v1/requests/{id}/actions/submit` with an `Idempotency-Key` header |
| Take the next request | `POST /api/v1/queue/claim-next` (officer) |
| Work it | `POST /api/v1/requests/{id}/actions/start`, then `resolve` |
| Track it | `GET /api/v1/requests/by-tracking/{number}`, Bangla digits accepted |
| Talk about it | `POST /api/v1/requests/{id}/comments`; staff may mark a comment `internal` |
| Attach a file | `POST /api/v1/requests/{id}/attachments` → `PUT` the file to the returned URL → `POST /api/v1/attachments/{id}/confirm`; it is checked, then downloadable |

Administration (an administrator with a two-step session):

| Task | Call |
|---|---|
| Departments, services, holidays, SLA suspensions | `/api/v1/admin/departments`, `/admin/categories`, `/admin/holidays`, `/admin/sla-suspensions` |
| Officers | `POST /api/v1/admin/users` (the officer sets their own password by SMS code), `PATCH` to deactivate |
| Assign | `POST /api/v1/requests/{id}/actions/assign` |
| All requests | `GET /api/v1/requests` with `status`, `category`, `department`, `officer`, `overdue` filters |
| Statistics | `GET /api/v1/admin/stats?by=department\|category\|officer`: each metric with the numbers that would show it being gamed |

Run the tests against the running stack:

```bash
docker build --target test -t grs-app:test .
docker run --rm --network grs-project_default \
  -e DATABASE_URL=postgres://grs_owner:owner-local@postgres:5432/grs \
  -e REDIS_CACHE_URL=redis://redis-cache:6379/1 \
  -e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
  -e S3_ENDPOINT=http://storage:8333 \
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
