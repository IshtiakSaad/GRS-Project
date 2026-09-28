# Government Service Request Management System

A system where citizens file service requests with government offices, officers work through them in order, and administrators run the whole thing. Built for people on cheap phones and slow connections, and for offices where accountability matters.

**Live demo: https://grs.root-access.xyz** (web app, Bangla and English) · API: https://grs.root-access.xyz/api/docs/ (synthetic data, reset every night)

Python 3.12 · Django 5.2 · Django REST Framework · PostgreSQL 17 · JWT · Redis · Celery · Nginx · Docker Compose · Next.js (static export) · Playwright

| | |
|---|---|
| Tests | 1,044 (unit, integration against real PostgreSQL, meta-tests), 97% coverage; Playwright end-to-end on a phone-sized browser: every screen and every action of the three roles. All run in CI on every push |
| Live checks | k6 load test, broker-outage chaos run, edge rate-limit check, backup restore: [results](#results-from-the-live-server) |
| Docs | [Architecture](docs/architecture.md) · [Decisions](docs/decisions/) · [Runbook](docs/runbook.md) · [Load tests](loadtest/README.md) |

---

## Try it

### On the live demo

Open https://grs.root-access.xyz and log in with an account below. Codes sent "by SMS" appear in the **Demo SMS inbox** linked at the top of every page.

For the API, open https://grs.root-access.xyz/api/docs/, call `POST /api/v1/auth/login`, copy `access` from the response, click **Authorize** and paste it.

| Role | Phone | Password |
|---|---|---|
| Citizen | `+8801000000101` … `+8801000000104` | `demo-password-2026` |
| Officer | `+8801000000011` … `+8801000000014` | `demo-password-2026` |
| Administrator | `+8801000000001` | `demo-password-2026` + a two-step code (secret available on request) |

Every number is on the unassigned `+880 10` prefix: nobody real can receive a message. Texts the system would send (codes, status updates) appear at `GET /api/v1/demo/sms/{phone}`; email lands at https://mail.grs.root-access.xyz. The database is wiped and reseeded at 03:00 Dhaka time.

### On your machine

Needs Docker with Compose v2. No cloud accounts.

```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose run --rm --no-deps api python manage.py seed_demo
```

| What | Where |
|---|---|
| Web app | http://localhost:8080 |
| API docs | http://localhost:8080/api/docs/ |
| Health | http://localhost:8080/health/ready |
| Email inbox (Mailpit) | http://localhost:8025 |

`seed_demo` prints the demo password and the administrator's two-step secret (add it to any authenticator app).

To work on the web app with hot reload, run `npm ci && npm run dev` in `web/` (http://localhost:3000; it proxies `/api` to the stack on :8080). The end-to-end tests run against the stack: `E2E_ADMIN_TOTP_SECRET=<secret from seed_demo> npx playwright test`.

Run the tests against the running stack:

```bash
docker build --target test -t grs-app:test .
docker run --rm --network grs-project_default \
  -e DATABASE_URL=postgres://grs_owner:owner-local@postgres:5432/grs \
  -e REDIS_CACHE_URL=redis://redis-cache:6379/1 -e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
  -e S3_ENDPOINT=http://storage:8333 grs-app:test
```

### A request's life

| Step | Who | Call |
|---|---|---|
| Log in | anyone | `POST /api/v1/auth/login` |
| Draft | citizen | `POST /api/v1/requests` (category code from `GET /api/v1/categories`) |
| Submit | citizen | `POST /api/v1/requests/{id}/actions/submit` with an `Idempotency-Key` header → a tracking number like `26-0000042-7` |
| Take the next one | officer | `POST /api/v1/queue/claim-next` |
| Work it | officer | `…/actions/start`, `request_info`, `resolve` or `reject` |
| Answer a question | citizen | `POST /api/v1/requests/{id}/comments` (answering resumes the clock) |
| Attach a file | anyone involved | `POST …/attachments` → `PUT` the file to the returned URL → `POST /api/v1/attachments/{id}/confirm` |
| Track it | citizen | `GET /api/v1/requests/by-tracking/{number}` (Bangla digits accepted) |
| See who looked | citizen | `GET /api/v1/requests/{id}/access-log` |

---

## The assignment, requirement by requirement

### Required features

| Requirement | How | Where | Tests |
|---|---|---|---|
| JWT login / register | Phone + password; register verifies the phone by SMS code. Access token 10 min, refresh tokens rotate, and reuse of an old one logs out every device | `apps/accounts/` | `auth/test_register.py`, `test_login.py`, `test_sessions.py`, `unit/test_tokens.py` |
| Roles: citizen, officer, admin | Role on the user; administrators also need a two-step (TOTP) login. Every endpoint declares its permission, and a meta-test fails if one does not | `accounts/permissions.py` | `auth/test_two_factor.py`, `meta/test_routes.py` |
| Create / view / update requests | Drafts are edited with `If-Match` versioning; after submission only the state machine changes a request | `service_requests/` | `requests/test_drafts_and_scope.py`, `test_submit.py` |
| Category, title, description, priority | Categories carry a service target in working days; priority can be set by staff | `directory/`, `service_requests/models.py` | `requests/test_actions.py` |
| Status | 8 states; every (state, action, role) combination is a table row, and database constraints reject impossible rows | `service_requests/transitions.py` | `requests/test_transition_matrix.py` (every cell), `db/test_constraints.py` |
| Officer assignment | Officers take the next request in priority order (`SKIP LOCKED`, so two officers never get the same one); admins can assign and reassign | `service_requests/services.py` | `requests/test_queue.py` |
| Comments | Public or internal (citizens never see internal notes, and see staff by role, not name) | `apps/collab/` | `collab/test_comments.py` |
| File attachment | Direct upload to object storage by signed URL; the server checks size, real file type and a virus-scanner interface before the file can be downloaded | `collab/storage.py`, `verification.py` | `collab/test_attachments.py`, `unit/test_scanning.py` |
| Manage categories | Admin CRUD for departments, categories, holidays and SLA suspensions; changes recompute open deadlines | `apps/admin_api/` | `admin/test_directory.py` |
| Assign officers | Create officers (they set their own password by SMS), deactivate, assign | `admin_api/services.py` | `admin/test_users.py`, `requests/test_actions.py` |
| View all requests | Admin list with filters (status, category, department, officer, overdue), keyset pagination | `service_requests/views.py` | `requests/test_drafts_and_scope.py` |
| Basic statistics | Volumes, resolution times and on-time rates by department, category or officer, each shown beside the number that would reveal it being gamed | `admin_api/stats.py` | `admin/test_stats.py` |

### Technical requirements

| Requirement | Where |
|---|---|
| Python, Django REST Framework, REST API | `src/` |
| PostgreSQL | Constraints, triggers, row locks, partitioned log tables, least-privilege roles: `deploy/postgres/`, migrations |
| JWT | `apps/accounts/tokens.py` (rotating signing keys) |
| Docker + Docker Compose | `Dockerfile` (multi-stage, non-root), `docker-compose.yml`, `docker-compose.prod.yml` |
| Git | Squash-merged pull requests, CI on every push (`.github/workflows/ci.yml`) |
| API documentation | OpenAPI 3 at `/api/docs/`; a test fails on any schema warning (`test_docs.py`) |
| Automated tests | `tests/`: 1,044 tests, 97% coverage |

### Bonus

| Bonus | How |
|---|---|
| Redis | Two instances split by failure behaviour: a broker that never evicts, and a cache that may evict anything and fails open |
| Celery | Notification delivery, file verification, deadline recompute, overdue escalation, audit sealing, cleanup |
| Email notifications and email verification | Verification link by email; request updates by email once verified (Mailpit in the demo) |
| Audit logs | Append-only (trigger + grants), hash-chained every minute, anchors copied to object storage; a separate log of which staff opened which request, visible to the citizen |
| Rate limiting | Nginx per address, plus per-phone and per-user limits in Redis |
| Frontend UI with live link | https://grs.root-access.xyz: 19 screens for citizen, officer and administrator, Bangla first, built for phones. Next.js exported to static files that the same Nginx serves; no Node server ([decision 9](docs/decisions/0009-static-web-app.md)). Playwright walks one request through every role in CI |

---

## What makes it hold up

- **Nothing is lost when a part fails.** Notifications are rows written in the same transaction as the change (an outbox); Redis only makes delivery faster. A sweeper redelivers what the queue lost, and a circuit breaker stops web requests from waiting on a dead broker.
- **The database refuses bad data.** Illegal states, missing fields for a state, self-review and edits to the audit log are rejected by PostgreSQL itself, not only by Python.
- **Officers cannot pick their cases.** They take the next one by priority and age; the choice cannot be steered.
- **A login rush cannot take the API down.** Password hashing runs on its own worker pool (`api-auth`).
- **Deadlines are honest.** Working days in Dhaka time, holidays, suspensions, and pauses while the office waits on the citizen. Late requests are escalated; late rejections and a sample of resolutions go to a review queue.
- **Retries are safe.** Submission takes an `Idempotency-Key`, so a lost response on 3G never creates a second request, and a similar request within minutes gets a duplicate warning.
- **Staff access is visible.** Every staff view, change and download is logged, and citizens can see which office looked at their request. Opening a request outside one's scope needs a stated reason (break-glass) and is reported.
- **Personal data stays home.** SMS and email carry only a tracking number and a status; files are stored on self-hosted object storage.

See [docs/architecture.md](docs/architecture.md) for how the pieces fit, and [docs/decisions/](docs/decisions/) for why.

---

## Results from the live server

AWS `m7i-flex.large` (2 vCPU, 8 GB), Mumbai, 28 September 2026. Load generated on the same machine, so the figures are conservative. Details: [loadtest/README.md](loadtest/README.md).

| Test | Result |
|---|---|
| Half storm: 15 logins/s, 30 browse/s, 3 submits/s | 72 req/s, **0 errors**; median 15–58 ms, p95 under 1 s (login 1.5 s) |
| Full storm (double) | Saturated at 86 req/s: slower (p95 8–11 s) but **0 of 9,763 requests failed** |
| Task broker stopped for 30 s under load | Submissions p95 **32 ms**, **0 of 401** failed, **401 of 401** notifications delivered after restart |
| One address hammering login | 10/s plus a burst of 40 reach the app; the rest get a JSON `429` with `Retry-After` |
| Nightly backup | Restores with identical counts; the restored audit chain verifies (4,887 rows) |

The chaos run found a real problem first: with the broker down, each submission waited on it and requests queued for up to 20 seconds. The circuit breaker in `apps/common/broker.py` is the fix.

---

## Built, and on the roadmap

**Built beyond the assignment:** SMS phone verification, admin two-step login with recovery codes, device trust modes, refresh grace window for lost responses, working-day SLA with pauses and suspensions, overdue escalation, review queue, idempotent submit, duplicate warning, staff access log and break-glass, hash-chained audit, a warm database standby (opt-in), health-checked deploys with rollback, nightly backup with a verified restore.

| Roadmap | Status today |
|---|---|
| Offline drafts and a lighter first load for 2G | The web app works on phones; drafts need a connection |
| Assisted submission (an officer files for a citizen, who confirms) | Schema, constraints and anomaly indexes exist; the endpoint refuses it for now |
| Real virus scanning (ClamAV) and image re-encoding | Scanner interface in place; the demo detects the EICAR test file |
| Write-once audit anchors on a separate host | Anchors are copied to object storage on the same host |
| In-app notification inbox; collapsing repeated status texts | Table columns and indexes exist |
| Phone number change; two-person rule for sensitive admin actions | Not started |
| Several SMS providers with failover; public anonymised statistics | One provider interface; admin statistics only |
| Point-in-time recovery (WAL archiving), zero-downtime deploys, alerts on service levels | Nightly dumps; deploys roll back on failure; structured logs with request IDs |

---

## Repository

```
src/apps/        accounts · service_requests · sla · collab · notifications · audit · admin_api · directory · common
tests/           unit · integration (real PostgreSQL) · meta (routes, migrations)
deploy/          nginx · postgres · gunicorn · scripts (bootstrap, deploy, backup, restore check, demo reset)
web/             Next.js app (static export) · e2e (Playwright)
loadtest/        k6 storm, chaos run, edge check
docs/            architecture · decisions · runbook
```
