# Government Service Request Management System

A citizen files a request with a government office from a phone. An officer works it. An administrator keeps the office honest. That is the assignment.

The real system lives in the details around it. The citizen is on a shared phone with 2G, reading Bangla, and reads her tracking number aloud over a bad line. Officers are under pressure to pick the easy cases, or the ones someone called about. Numbers that look good can be gamed without anyone lying. Someone with database access could quietly rewrite what happened. This repository is a working answer to that problem, built so that each claim below is proven by something that runs.

**Live demo: https://grs.root-access.xyz** (Bangla first, English one tap away) · API: https://grs.root-access.xyz/api/docs/ · synthetic data, reset every night

Python 3.12 · Django 5.2 · Django REST Framework · PostgreSQL 17 · JWT · Redis · Celery · Nginx · Docker Compose · Next.js (static export) · Playwright · ClamAV · WAL-G

| | |
|---|---|
| Tests | 1,081 backend tests (unit, integration against real PostgreSQL, meta-tests), 96% line coverage. 25 Playwright tests on a phone-sized browser, covering every screen and every action of the three roles. All run in CI on every push, with the malware scanner tested against real ClamAV. |
| Proven live | Load storm, a broker outage under load, the edge rate limit, a nightly restore to a chosen moment: [results](#results-from-the-live-server) |

---

## Where to start

| You have | Read |
|---|---|
| 5 minutes | [Try it](#try-it) below, then the [tour](#a-ten-minute-tour-of-the-live-demo) |
| 20 minutes | [The problem, before the code](docs/problem.md): who uses it, the ground it runs on, how offices go wrong, who might attack it, and what we assumed. Then [from finding to proof](docs/traceability.md), which follows each finding to the test that proves the response holds |
| An hour | [Architecture](docs/architecture.md) · [17 decision records](docs/decisions/), each with the alternatives we rejected · [Scope](docs/scope.md): what v1 leaves out, and why · [Runbook](docs/runbook.md) · [Load and chaos tests](loadtest/README.md) |

---

## The problem in one screen

- **The citizen** files from a phone, often a shared one, on a connection that drops. So a lost response must never cost a second request (idempotent submit). A shared computer gets a short session by default. Her tracking number carries a check digit that catches every single wrong digit and every swapped pair, the two mistakes people make reading numbers aloud. Every status change reaches her by SMS, the one channel every phone has.
- **The officer** does not choose what to work on. The queue gives the most urgent request in the department, so easy and favoured cases cannot jump the line. The citizen sees which office looked at her request, never the officer's name, so decisions stay the office's.
- **The administrator** sees statistics that cannot be gamed quietly. The on-time rate is shown beside how often the clock was paused and how many requests were rejected near the deadline. Late rejections and a sample of resolutions go to review.
- **Nobody rewrites history.** Every staff look is recorded, and so is every change. The audit log is hash-chained, and its checkpoints are locked in write-once storage that root on the server cannot delete.
- **The operator** is one person, asleep at 3 a.m. Alerts reach a phone only when a target is really at risk. The database streams to a separate bucket every minute, and a restore drill runs every night.

The full picture, with the reasoning, is in [docs/problem.md](docs/problem.md).

---

## Try it

### On the live demo

Open https://grs.root-access.xyz and log in with an account below. The app opens in Bangla; tap **English** at the top to switch. Codes and texts the system would send by SMS appear in the **Demo SMS inbox**, linked at the top of every page.

| Role | Phone | Password |
|---|---|---|
| Citizen | `+8801000000101` … `+8801000000104` | `demo-password-2026` |
| Officer, Birth and Death Registration | `+8801000000011`, `+8801000000012` | `demo-password-2026` |
| Officer, Land Office | `+8801000000013` | `demo-password-2026` |
| Officer, Trade Licence Section | `+8801000000014` | `demo-password-2026` |
| Administrator | `+8801000000001` | `demo-password-2026` + a two-step code (the secret is available on request) |

Every number is on the unassigned `+880 10` prefix, so no real person can receive a message. A live deployment refuses that prefix, and the demo accepts nothing else. Email is real: add your own address under Profile and the verification link arrives in your inbox, sent through Resend from `no-reply@grs.root-access.xyz` (three verification emails per account a day, and a daily cap for the whole demo, since anyone can type any address). The database is wiped and reseeded at 03:00 Dhaka time.

For the API: open https://grs.root-access.xyz/api/docs/. The reference starts with how to log in and the rules every endpoint follows, then lists the endpoints in the order a request meets them. Try `POST /api/v1/auth/login`, copy `access` from the answer into the **Bearer** field under Authentication, and every call you try after that is made as that user.

### A ten-minute tour of the live demo

1. **File a request as a citizen** (`+8801000000102`). Choose **New request** → *Birth certificate correction*, fill it in, submit. You get a tracking number like `26-0000042-7`. Open the Demo SMS inbox: the text carries the number and the status, nothing else ([why](docs/decisions/0012-texts-carry-no-personal-data.md)). Now go to **Track**, type the number with one digit wrong, and it is refused before any lookup.
2. **Work it as an officer** (`+8801000000011`, same department). Open **Queue** and press **Take the next request**. You may not get the one you just filed: you get the most urgent one waiting ([why](docs/decisions/0003-officers-take-the-next-request.md)). The list below the button shows the order the requests will be taken in. **Start work**, then **Ask the citizen** a question: the deadline clock pauses.
3. **Answer as the citizen.** The request shows what the office asked. **Send your answer** and the clock resumes. Open **Who looked**: you see an office and a role, never a name ([why](docs/decisions/0017-staff-access-is-visible.md)).
4. **Look as an administrator.** The **Dashboard** shows each statistic beside the number that would expose it being gamed ([why](docs/decisions/0016-every-statistic-has-a-counterweight.md)). **Reviews** holds late rejections and a sample of resolutions. The break-glass report lists every time an officer opened a request outside their department, with the reason given.

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

`seed_demo` prints the demo password and the administrator's two-step secret; add the secret to any authenticator app. Locally, uploads are checked by a small stand-in that flags the EICAR test file just as ClamAV does, so the stack runs without ClamAV's 1.5 GB of memory; production uses ClamAV itself, and `docker compose --profile full up -d clamav` starts it locally.

To work on the web app with hot reload, run `npm ci && npm run dev` in `web/` (http://localhost:3000; it proxies `/api` to the stack on :8080). The end-to-end tests run against the stack: `E2E_ADMIN_TOTP_SECRET=<secret from seed_demo> npx playwright test`.

Run the backend tests against the running stack:

```bash
docker build --target test -t grs-app:test .
docker run --rm --network grs-project_default \
  -e DATABASE_URL=postgres://grs_owner:owner-local@postgres:5432/grs \
  -e REDIS_CACHE_URL=redis://redis-cache:6379/1 -e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
  -e S3_ENDPOINT=http://storage:8333 grs-app:test
```

### A request's life, through the API

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
| JWT login / register | Phone + password; registration verifies the phone by SMS code. Access tokens last 10 minutes; refresh tokens rotate, and reusing an old one logs out every device. Session length depends on whose device it is ([decision 14](docs/decisions/0014-sessions-follow-the-device.md)) | `apps/accounts/` | `auth/test_register.py`, `test_login.py`, `test_sessions.py`, `unit/test_tokens.py` |
| Roles: citizen, officer, admin | Role on the user; administrators also need a two-step (TOTP) login. Every endpoint declares its permission, and a meta-test fails if one does not | `accounts/permissions.py` | `auth/test_two_factor.py`, `meta/test_routes.py` |
| Create / view / update requests | Drafts are edited with `If-Match` versioning; after submission only the state machine changes a request | `service_requests/` | `requests/test_drafts_and_scope.py`, `test_submit.py` |
| Category, title, description, priority | Categories carry a service target in working days; priority can be set by staff | `directory/`, `service_requests/models.py` | `requests/test_actions.py` |
| Status | 8 states. Every combination of state, action and role is a row in one table, and database constraints reject impossible rows | `service_requests/transitions.py` | `requests/test_transition_matrix.py` (every cell), `db/test_constraints.py` |
| Officer assignment | Officers take the next request in priority order (`SKIP LOCKED`, so two officers never get the same one); admins can assign and reassign, on the record | `service_requests/services.py` | `requests/test_queue.py` |
| Comments | Public or internal. Citizens never see internal notes, and see staff by role, not name | `apps/collab/` | `collab/test_comments.py` |
| File attachment | Direct upload to object storage by signed URL. The server checks the size, scans the file with ClamAV and reads its real type from its bytes before it can be downloaded | `collab/storage.py`, `verification.py`, `scanning.py` | `collab/test_attachments.py`, `unit/test_scanning.py`, `unit/test_clamd.py` (also against real ClamAV in CI) |
| Manage categories | Admin CRUD for departments, categories, holidays and office closures; changes recompute the deadlines of open requests | `apps/admin_api/` | `admin/test_directory.py` |
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
| Automated tests | `tests/`: 1,081 tests, 96% coverage; `web/e2e/`: 25 browser tests |

### Bonus

| Bonus | How |
|---|---|
| Redis | Two instances split by how they may fail: a broker that never evicts, and a cache that may evict anything and fails open ([decision 4](docs/decisions/0004-two-redis-instances.md)) |
| Celery | Notification delivery, file verification, deadline recompute, overdue escalation, audit sealing, cleanup |
| Email notifications and email verification | Verification link by email; request updates by email once the address is verified. Delivered to real inboxes through an SMTP relay (Resend on the demo); Mailpit catches everything locally |
| Audit logs | Append-only (trigger + grants), hash-chained every minute, checkpoints locked in write-once storage. A separate log of which staff opened which request, visible to the citizen |
| Rate limiting | Nginx per address, plus per-phone and per-user limits in Redis |
| Frontend UI with live link | https://grs.root-access.xyz: 21 pages for citizen, officer and administrator, Bangla first, built for phones. Next.js exported to static files that the same Nginx serves, with no Node server ([decision 9](docs/decisions/0009-static-web-app.md)). Playwright walks one request through every role in CI |

---

## What makes it hold up

- **Nothing is lost when a part fails.** Notifications are rows written in the same transaction as the change they announce (an outbox); Redis only makes delivery faster. A sweeper redelivers what the queue lost, and a circuit breaker stops web requests from waiting on a dead broker.
- **The database refuses bad data.** Illegal states, missing fields for a state, self-review and edits to the audit log are rejected by PostgreSQL itself, not only by Python.
- **Officers cannot pick their cases.** They take the next one by priority, deadline and age; the choice cannot be steered.
- **A login rush cannot take the API down.** Password hashing runs on its own worker pool (`api-auth`).
- **Deadlines are honest.** Working days in Dhaka time, holidays, office closures, and pauses while the office waits on the citizen. Late requests are escalated; late rejections and a sample of resolutions go to a review queue.
- **Retries are safe.** Submission takes an `Idempotency-Key`, so a lost response on 3G never creates a second request, and the same request twice within minutes asks before filing it again.
- **Staff access is visible.** Every staff view, change and download is logged, and citizens can see which office looked at their request. Opening a request outside one's department needs a stated reason (break-glass) and is reported.
- **No file is trusted.** Every upload is scanned by ClamAV and its real type read from its bytes before anyone can download it. If the scanner is down, files wait; none is approved unscanned.
- **Problems reach a person.** Availability and latency are measured from every request Nginx serves. Burn-rate alerts, stuck messages, stuck uploads, and disk and certificate problems go to a phone, and an outside check covers the server going dark.
- **A lost server loses about a minute.** The database ships its changes to a write-once bucket every minute. Each night, and on every push in CI, a drill restores from that bucket alone to a chosen moment and checks the result. Audit checkpoints sit in the same locked storage, so even root on the server cannot rewrite history unnoticed. On the live demo that bucket is on AWS S3 in Mumbai, reached through the server's instance role: no key is stored on the server.
- **Personal data stays home.** SMS and email carry only a tracking number and a status; files are kept on storage the office runs itself.

How the pieces fit: [docs/architecture.md](docs/architecture.md). Why each one is the way it is, and what we rejected: [docs/decisions/](docs/decisions/).

---

## Results from the live server

AWS `m7i-flex.large` (2 vCPU, 8 GB), Mumbai, 28 September 2026. The load was generated on the same machine, sharing its CPUs, so the figures are conservative. Details: [loadtest/README.md](loadtest/README.md).

| Test | Result |
|---|---|
| Half storm: 15 logins/s, 30 browse/s, 3 submits/s | 72 req/s, **0 errors**; median 15–58 ms, p95 under 1 s (login 1.5 s) |
| Full storm (double) | Saturated at 86 req/s: slower (p95 8–11 s), but **0 of 9,763 requests failed** |
| Task broker stopped for 30 s under load | Submissions p95 **32 ms**, **0 of 401** failed, **401 of 401** notifications delivered after restart |
| One address hammering login | 10/s plus a burst of 40 reach the app; the rest get a JSON `429` with `Retry-After` |
| Nightly backup | Restores with identical counts; the restored audit chain verifies (4,887 rows) |
| Point-in-time recovery (nightly and in CI) | Restored from the archive bucket alone to a named moment in 7 s; counts match and the audit chain verifies against its locked copies |

The chaos run found a real problem before it found none. With the broker down, each submission waited on it, and requests queued for up to 20 seconds. The circuit breaker in `apps/common/broker.py` is the fix; the numbers above are after it.

Testing against the real thing corrected us twice more. Real ClamAV recognises the EICAR test file only at the very start of a file, where our first stand-in had found it anywhere; the stand-in now matches ClamAV, and the scan runs before the type check so a disguised file is caught as malware, not as a wrong type. And the browser tests caught the web app signing people out when the server answered "slow down" (`429`); it now retries and only a real `401` ends a session.

---

## Scope

Version 1 is the smallest system in which every claim is proven by something that runs. Where a feature could not be built and proven to that standard, it was left out, and the ground was prepared for it instead: assisted filing at a counter, image re-encoding, phone number change, a second SMS provider, public statistics. [docs/scope.md](docs/scope.md) gives the reason for each and what would bring it in, along with what is deliberately left to people.

---

## Repository

```
src/apps/        accounts · service_requests · sla · collab · notifications · audit · admin_api · directory · monitoring · common
tests/           unit · integration (real PostgreSQL) · meta (routes, migrations)
deploy/          nginx · postgres (pgaudit, WAL-G) · gunicorn · scripts (bootstrap, deploy, backup, restore drills, demo reset)
web/             Next.js app (static export) · e2e (Playwright)
loadtest/        k6 storm, chaos run, edge check
docs/            problem · traceability · architecture · decisions · scope · runbook
```
