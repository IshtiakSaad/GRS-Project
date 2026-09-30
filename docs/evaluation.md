# Evaluation

What we claim about this system, how each claim was tested, what the tests found, and where their reach ends. It is written like the evaluation section of a systems paper: questions first, then for each one the method, the results and the threats to validity, then the decisions the results support. Every number here comes from a run that can be repeated with the commands in [section 13](#13-reproducing-every-number).

Where the evidence went against us, the finding is reported as it came out. Two results changed the code ([section 5](#5-q3-does-a-dead-task-broker-take-submissions-down-with-it) and [section 12](#12-what-testing-against-the-real-thing-corrected)), one corrects a decision record ([section 8](#8-q6-does-the-tracking-number-catch-the-mistakes-people-make)), and one is a weakness we did not fix ([section 9](#9-q7-what-does-a-phone-download-on-a-slow-connection)).

---

## Contents

1. [Questions](#1-questions)
2. [System under test](#2-system-under-test)
3. [Q1. Is the behaviour correct, and how do we know?](#3-q1-is-the-behaviour-correct-and-how-do-we-know)
4. [Q2. How much load does one server carry, and how does it fail?](#4-q2-how-much-load-does-one-server-carry-and-how-does-it-fail)
5. [Q3. Does a dead task broker take submissions down with it?](#5-q3-does-a-dead-task-broker-take-submissions-down-with-it)
6. [Q4. Does the edge stop one address flooding the login?](#6-q4-does-the-edge-stop-one-address-flooding-the-login)
7. [Q5. Can the data be recovered, and can history be rewritten?](#7-q5-can-the-data-be-recovered-and-can-history-be-rewritten)
8. [Q6. Does the tracking number catch the mistakes people make?](#8-q6-does-the-tracking-number-catch-the-mistakes-people-make)
9. [Q7. What does a phone download on a slow connection?](#9-q7-what-does-a-phone-download-on-a-slow-connection)
10. [Q8. What does a password cost, and what does that cap?](#10-q8-what-does-a-password-cost-and-what-does-that-cap)
11. [Q9. Which attacks do the tests show are closed?](#11-q9-which-attacks-do-the-tests-show-are-closed)
12. [What testing against the real thing corrected](#12-what-testing-against-the-real-thing-corrected)
13. [Reproducing every number](#13-reproducing-every-number)
14. [Decisions and the evidence behind them](#14-decisions-and-the-evidence-behind-them)
15. [Threats to validity](#15-threats-to-validity)
16. [Summary](#16-summary)

---

## 1. Questions

The [problem](problem.md) names the people the system serves and the ways an office goes wrong. Each question turns one of those into something that can be measured.

| # | Question | Why it matters | Kind of evidence |
|---|---|---|---|
| Q1 | Does the system do what the rules say, and refuse what they forbid? | A request system that can reach an illegal state is not trusted twice. | Automated tests, database constraint tests, browser tests |
| Q2 | How much load does one server carry, and what happens past it? | Offices open at 9 a.m., and everyone logs in at once. | Load test on the live server |
| Q3 | If the task broker dies, do submissions still succeed, and is every message still delivered? | A lost status message is, to the citizen, a change that never happened. | Chaos test on the live server |
| Q4 | Is one address flooding the login stopped before it costs CPU? | Password hashing is slow on purpose, so a flood is cheap for the attacker. | Edge test from outside, over the internet |
| Q5 | After losing the server, what can be restored, how much is lost, and can the audit trail be rewritten? | The records of state decisions must outlive the machine and resist quiet edits. | Nightly restore drills, tamper tests |
| Q6 | Does a tracking number read aloud catch the mistakes people make? | A mistyped number must not open someone else's request. | Error-detection experiment |
| Q7 | What does a phone download to open the app on 2G or 3G? | The citizen's connection is the slowest part of the system. | Build measurement |
| Q8 | What does one password check cost, and what does that cost cap? | It sets the login ceiling and the price of a login flood. | Benchmark, and a calculation |
| Q9 | Which attacks do the tests show are closed? | A security claim is only as good as the test that tries the attack. | Security tests |

---

## 2. System under test

| | |
|---|---|
| Code | `main` at `d6b39e4` (30 September 2026), plus this change |
| Backend | Python 3.12, Django 5.2, Django REST Framework, Gunicorn sync workers (`api` 3, `api-auth` 2), Celery |
| Data | PostgreSQL 17 with pgaudit and data checksums; two Redis instances (broker, cache); SeaweedFS (S3 API) for files |
| Edge | Nginx: TLS, buffering, rate limits, the static web app |
| Web | Next.js 16.3.6 (static export), React 19.3 |
| Tools | k6 1.3.0 (load), Playwright 1.63 (browser: Chromium, Pixel 7 profile), pytest with coverage |

Two machines produced the numbers, and every figure says which.

| Machine | Used for |
|---|---|
| **Live server**: AWS EC2 `m7i-flex.large`, 2 vCPU, 8 GB, ap-south-1 (Mumbai) | Load, chaos and edge tests (28 September 2026); restore drills; the hash cost the configuration was set from |
| **Laptop**: Intel Core i5-1135G7 (4 cores, 8 threads), Docker Desktop on Windows 10 | Test suite and coverage, the hash benchmark rerun, the check-digit experiment, page weights (30 September 2026) |

**The timeout ladder.** Each layer gives up before the one above it, so a slow query ends as a clean error rather than a hung worker.

| Layer | Limit | Set in |
|---|---|---|
| PostgreSQL statement (API role) | 5 s; lock wait 2 s; idle in a transaction 10 s | `deploy/postgres/roles.sql` |
| Gunicorn worker | 15 s | `deploy/gunicorn/api.py` |
| Nginx to the application | 20 s read; 3 s connect | `deploy/nginx/grs/api.conf` |

---

## 3. Q1. Is the behaviour correct, and how do we know?

### Method

The backend suite runs against real PostgreSQL 17 (not SQLite), real Redis and real object storage, in the image that ships. The browser suite drives the built web app through Nginx on a phone-sized Chromium.

Four kinds of test carry most of the weight:

- **The transition matrix.** Every combination of the 8 states, 14 actions and 4 kinds of actor is a row in one table (`apps/service_requests/transitions.py`). One test walks every cell and asserts the action is allowed exactly where the table says, and refused everywhere else (`tests/integration/requests/test_transition_matrix.py`). Another fails if the API offers an action the matrix does not cover (`test_the_matrix_covers_every_action_the_api_offers`).
- **The database as the last line.** Tests go around the application and insert illegal rows directly: a resolved request with no resolution note, a second open pause, a reviewer reviewing themselves, an update to the audit log. PostgreSQL itself must refuse each one (`tests/integration/db/`).
- **Meta-tests** check the code's shape: every route declares its permission (`tests/meta/test_routes.py`); every route that hashes a password is sent by Nginx to the `api-auth` pool (`test_bulkhead_routes_include_every_password_route`); every model change has a migration; every migration after the first is safe to run under live traffic (`tests/meta/test_migrations.py`).
- **Browser flows** walk each role through every screen. A citizen registers, confirms, files with a document, answers a question, and sees the outcome and who looked. An officer claims, works and resolves. An administrator assigns, reviews, edits the directory, and adds an officer who then sets a password from the welcome text.

### Results

| Suite | Tests | Machine |
|---|---|---|
| Unit | 114 | Laptop |
| Integration (real PostgreSQL, Redis, storage) | 980 | Laptop |
| Meta (routes, migrations, bulkhead) | 18 | Laptop |
| **Backend total** | **1,112** (1,111 passed, 1 skipped\*), **65.6 s** with coverage | Laptop |
| Browser: flows through every role | 26 | CI |
| Browser: screenshots of every screen | 4 | CI |

\* The skipped test talks to a ClamAV daemon on a configured host. CI runs it against real ClamAV in a job of its own.

**Line coverage: 96%** (4,651 statements, 183 not run), over `apps` and `config`.

For scale: 8,571 non-blank lines of Python in `src/` (without migrations) and 5,347 of TypeScript in `web/src/`, tested by 5,190 lines of Python tests and 611 lines of browser tests.

### Threats to validity

- Line coverage says a line ran, not that its behaviour was checked. We set no branch-coverage target and did no mutation testing.
- The transition matrix is exhaustive over the table, but the table encodes our reading of how an office works. No office reviewed it.
- The browser tests use Chromium only, on an emulated phone screen, over a fast local network.

---

## 4. Q2. How much load does one server carry, and how does it fail?

### Method

`loadtest/storm.js` (k6) runs three scenarios at once, shaped like the 9 a.m. rush: a login burst, citizens browsing their requests, and new requests filed with an `Idempotency-Key`. Each virtual user logs in as a different synthetic citizen (900 seeded), so per-phone and per-account limits apply as they would to real people. k6 calls the application containers directly, so the result measures the application, not the per-address limit that a single load generator would hit (that is Q4).

| Scenario | Full storm (`SCALE=1`) | Pass mark |
|---|---|---|
| `login_burst` | ramps to 30 logins/s, holds 1 minute | p95 < 2 s |
| `browse` | 60 iterations/s: list my requests, open one | p95 < 500 ms, < 1% errors |
| `submit` | 5 new requests/s: draft, then submit | p95 < 1 s, < 1% errors |

The half storm (`SCALE=0.5`) halves every rate.

### Results (live server, 28 September 2026)

| Load | Throughput | Browse p50 / p95 | Submit p50 / p95 | Login p50 / p95 | Errors |
|---|---|---|---|---|---|
| Half storm | 72 req/s | 15 ms / 0.86 s | 41 ms / 0.96 s | 58 ms / 1.47 s | **0 of 7,775** |
| Full storm | 86 req/s (saturated; k6 dropped 3,214 planned iterations) | 2.9 s / 8.0 s | 3.0 s / 8.5 s | 7.6 s / 11.1 s | **0 of 9,763** |

**Finding.** Two vCPUs carry about 70–85 requests a second. Past that, the system slows down instead of failing: at twice its capacity, not one of 9,763 requests returned an error. The timeout ladder and Nginx's buffering do that job; a request waits rather than being dropped.

The half storm met every pass mark. The full storm met none of its latency marks, as expected at twice the capacity.

### Threats to validity

- **k6 ran on the same two CPUs as the application.** The load generator took CPU from what it measured, so the true capacity is somewhat higher. We report the conservative figure.
- **Each configuration was run once.** There are no confidence intervals.
- **The workload is synthetic.** Its mix (login-heavy, few submissions) is our guess at a morning peak, not a recording of real traffic.
- **The database was small** (about 1,200 requests after the runs). Query times on a year of real data were not measured.

---

## 5. Q3. Does a dead task broker take submissions down with it?

### Method

`loadtest/chaos.sh` runs steady submissions (4 a second) and stops `redis-broker` for 30 seconds in the middle. It counts failed submissions, the latency while the broker was down, and whether every notification the submissions created was delivered after the restart.

### Results

The first run found a real problem. No notification was lost: the rows waited in PostgreSQL (the outbox, [decision 2](decisions/0002-notifications-through-an-outbox.md)) and the sweeper delivered them once the broker returned. But submissions slowed badly. Each one waited about 4 s per message for the dead broker (Celery's default connection timeout), and the sync workers queued behind each other.

The fix is a circuit breaker in each process (`apps/common/broker.py`): after one failed enqueue, the process stops trying for 30 s and leaves the work to the sweepers. The connection timeout is now 1 s.

| While the broker was down | Before the fix (laptop) | After (laptop) | After (live server) |
|---|---|---|---|
| Submit p95 | 11.7 s | 99 ms | **32 ms** |
| Worst request | 20 s | 4 s (the first probe per worker) | 62 ms |
| Failed submissions | not recorded | 0 of 401 | **0 of 401** |
| Notifications delivered after the restart | all | 401 of 401, within 65 s | **401 of 401, within 30 s** |

**Finding.** With the outbox, a broker outage delays messages and loses none. Without the circuit breaker, it also made every submission slow. With it, the outage is invisible to the citizen.

### Threats to validity

The outage was one 30-second stop of one component. A slow broker (up but degraded), a network partition, and a PostgreSQL outage were not tested.

---

## 6. Q4. Does the edge stop one address flooding the login?

### Method

`loadtest/edge-check.js`, run from Dhaka over the internet against the public site: 60 login attempts a second from one address for 10 seconds, 600 in all.

### Results (live server)

| | Expected from the configuration | Measured |
|---|---|---|
| Reached the application | 10/s for 10 s, plus a burst of 40 = 140 | **138** |
| Refused at Nginx | 460 | **462**, each with the API's JSON `RATE_LIMITED` body and `Retry-After` |

**Finding.** The edge limit behaves as configured, within two requests (the difference is timing at the edges of the window). A refused attempt costs no password hash.

### Threats to validity

This shows the limit works for one address. It says nothing about many: a botnet with each address under the limit gets through, and every attempt is hashed ([limitations](limitations.md#3-security-where-the-defences-stop)).

---

## 7. Q5. Can the data be recovered, and can history be rewritten?

### Method

Three drills run every night on the live server and on every push in CI:

- **Backup and restore** (`deploy/scripts/restore-check.sh`): restore last night's backup into an empty container and compare row counts with the live database.
- **Point-in-time recovery** (`deploy/scripts/pitr-check.sh`): mark a named restore point in the live database, restore from the off-host bucket alone to exactly that point, and check the counts and the audit chain.
- **Audit verification** (`manage.py verify_audit`): recompute the hash chain and compare it with the checkpoints locked in write-once storage.

Tamper tests (`tests/integration/test_audit_seal.py`) attack the audit log directly: edit a row, rewrite every hash after it, cut rows off the end, rewrite the database's own copy of the checkpoints.

### Results

| Drill | Result |
|---|---|
| Restore of a backup taken right after the load tests | Identical counts: 1,219 requests, 4,887 audit rows, 909 users. The restored chain verified all 4,887 rows. |
| Point-in-time recovery | Restored from the bucket alone to a named moment in **7 s**. Counts match, and the chain verifies against its locked copies. |
| **Recovery point** | At most **60 s** of writes lost with the server: PostgreSQL closes a WAL segment at least every minute (`archive_timeout = 60`) and ships it off the host. |

| Tamper attempt | Caught by |
|---|---|
| Edit one audit row | The chain check: every hash after it breaks (`test_rows_are_chained_in_order`) |
| Rewrite that row and every later hash | `test_a_rewritten_chain_still_differs_from_its_anchor` |
| Delete the newest rows | `test_cutting_off_the_end_of_the_chain_is_caught` |
| Rewrite the database and its own checkpoints | `test_rewriting_the_database_and_its_anchors_is_caught_off_the_host` |
| A checkpoint that never reached the bucket | `test_anchors_missing_off_the_host_are_caught` |
| The API's database role touching checkpoints | `test_api_cannot_touch_anchors_or_migrations` |

**Finding.** Recovery is practised, not assumed, and it works at demo size. History cannot be rewritten without disagreeing with copies that the server's own credentials cannot change.

### Threats to validity

- 7 s is at demo size. Restore time grows with the database and with the WAL written since the last base backup; it was not measured on a large database.
- Rebuilding after losing the whole server (a new machine, the restore, moving DNS) has not been timed end to end.
- On the demo, the locks are in GOVERNANCE mode for 7 days, so the AWS account holder with a bypass permission could remove them. COMPLIANCE mode, which nobody can bypass, is one setting away.

---

## 8. Q6. Does the tracking number catch the mistakes people make?

### Method

A tracking number such as `26-0000034-2` ends in a check digit, so a mistyped number is refused before any lookup instead of opening another person's request. The scheme that computes that digit decides which mistakes are caught.

`tools/bench_check_digit.py` takes 5,000 tracking-number bodies (year 26, random serial, seed 2026). For each, it generates every corrupted version in each error class of Verhoeff's 1969 study of how people get digits wrong, and counts how many each scheme refuses. It compares our scheme (Damm) with Verhoeff's own scheme, Luhn (bank cards) and a plain digit sum. Each implementation was first checked against published values (Damm 572 → 4, Verhoeff 236 → 3, Luhn 7992739871 → 3).

### Results (laptop)

Share of corrupted numbers refused. Higher is better.

| Error class | Cases\* | **Damm** (used) | Verhoeff | Luhn | Digit sum |
|---|---|---|---|---|---|
| One digit wrong (5 → 8) | 450,000 | **100.00%** | 100.00% | 100.00% | 100.00% |
| Neighbours swapped (12 → 21) | 41,117 | **100.00%** | 100.00% | 98.30% | 0.00% |
| Jump swap (123 → 321) | 36,035 | 89.70% | 95.25% | 0.00% | 0.00% |
| Twin (11 → 22) | 34,947 | 91.22% | 94.83% | 92.72% | 88.89% |
| Jump twin (121 → 323) | 35,685 | 85.94% | 95.07% | 88.89% | 88.89% |
| Phonetic (13 → 30) | 6,196 | 97.53% | 82.94% | 88.30% | 100.00% |
| Any other number | 100,000 | 89.89% | 89.77% | 90.19% | 90.02% |

\* Cases for Damm. Each scheme has its own check digit, so its set of corrupted numbers differs slightly.

**Findings.**

1. **Damm catches every one-digit mistake and every swap of neighbours**, the two most common mistakes when a number is read aloud. So does Verhoeff. Luhn misses 1.7% of swaps (`09` ↔ `90`), and a digit sum catches no swaps at all.
2. **No single check digit does better than about 90% against a completely wrong number.** One digit has ten values, so one wrong number in ten passes by chance. The check digit guards against slips, not guessing. Guessing is stopped elsewhere: a request outside the user's scope answers 404.
3. **Verhoeff beats Damm on the rarer classes** (jump swaps, twins, jump twins, by 4 to 9 points) and loses on phonetic slips (83% against Damm's 98%). This corrects [decision 15](decisions/0015-tracking-numbers-are-read-aloud.md), which said Verhoeff "catches the same errors". It does on the two classes that matter most, and differs on the rest. We keep Damm: it is one table and a loop, and it is the better of the two on the one class specific to numbers heard over a phone.

### Threats to validity

- The error classes come from research on English speakers. How people misread and mishear **Bangla** digits was not studied, and the phonetic class (thirteen and thirty) is an English confusion.
- The classes are counted separately. In real use they occur at very different rates (Verhoeff found single errors and neighbour swaps to be most of all errors), so the table is not one overall score.

---

## 9. Q7. What does a phone download on a slow connection?

### Method

`tools/measure_page_weight.py` reads the static build and, for every page, adds up the HTML and every script and stylesheet it references, gzipped at level 9 as Nginx serves them. It divides by three connection speeds. It counts transfer only: no round trips, no TLS setup and no time for the phone to run the scripts, so a real first load is slower.

### Results (laptop build, 24 pages)

| | Size (gzip) | 2G / EDGE, 100 kbps | Slow 3G, 400 kbps | 4G, 9 Mbps |
|---|---|---|---|---|
| First visit to a page (median) | 199.2 KB | **16.3 s** | 4.1 s | 0.2 s |
| Heaviest page (a request's detail) | 204.1 KB | 16.7 s | 4.2 s | 0.2 s |
| Shared by every page, cached after the first | 194.5 KB | | | |
| Each further page | 2–10 KB | under 1 s | | |

**Finding: this is a weakness.** The [problem](problem.md) puts the citizen on 2G, and there the first visit costs about 16 seconds of transfer before the phone starts running the page. Almost all of it is the framework (React and Next.js), shared by every page and cached after the first. Each page after that is cheap. We did not fix this; the [limitations](limitations.md#5-the-citizens-experience) say what would.

### Threats to validity

The speeds are labels, not measurements of Bangladeshi networks. Real 2G throughput varies widely, and latency, which this ignores, dominates on 2G.

---

## 10. Q8. What does a password cost, and what does that cap?

### Method

`tools/bench_password_hash.py` times 20 hashes (after one warm-up) of each candidate setting on one CPU. The configuration was set from a run on the live server; it was rerun on the laptop for this report.

### Results (laptop, one CPU)

| Setting | Median | Worst | Logins per second per core |
|---|---|---|---|
| **Argon2id, 19 MiB, 2 passes, 1 lane (used; the OWASP minimum)** | **24.6 ms** | 28.0 ms | **40.6** |
| Argon2id, 46 MiB, 1 pass (OWASP alternative) | 44.7 ms | 84.5 ms | 22.4 |
| Argon2id, 64 MiB, 3 passes | 151.4 ms | 163.1 ms | 6.6 |
| Argon2id, 100 MiB, 2 passes, 8 lanes (Django's default) | 295.7 ms | 415.5 ms | 3.4 |
| PBKDF2-SHA256, 1,000,000 rounds (Django 5.2's default) | 282.3 ms | 304.4 ms | 3.5 |

On the live server, the setting in use measured about 23 ms.

**What that caps (a calculation, not a measurement).** Two `api-auth` workers at about 23 ms a hash check about 85 passwords a second. The half storm's 15 logins a second used under a fifth of that; its login p95 of 1.47 s came from both pools sharing two CPUs with everything else.

**Why the minimum and not more.** Every step up multiplies the cost of each 9 a.m. login by the same factor it costs an attacker holding a stolen database. Django's default Argon2 setting would cut the login ceiling on this server from about 85 a second to about 7. The OWASP minimum is memory-hard, which bcrypt and PBKDF2 are not, and raising it later is safe: a password is rehashed with the new setting at its owner's next login.

---

## 11. Q9. Which attacks do the tests show are closed?

Each row is an attack that a test performs. The test fails if the attack works.

| Attack | Defence | Test |
|---|---|---|
| Learn which numbers have accounts, by registering | The same answer and the same hashing cost either way; the real owner is warned by SMS, at most once an hour | `test_existing_number_gets_the_same_answer_and_its_owner_is_warned` |
| … by logging in | A wrong password and an unknown number look identical, and are delayed on the same schedule | `test_wrong_password_and_unknown_phone_look_identical`, `test_unknown_numbers_are_delayed_on_the_same_schedule` |
| … by resending codes or resetting a password | The same answer for unknown, verified and dormant numbers | `test_resend_for_unknown_or_verified_numbers_looks_the_same`, `test_reset_answers_the_same_for_unknown_and_dormant_numbers` |
| Lock an officer out with wrong passwords | No lockout, a growing delay; the officer's own device has its own counter | `test_attacker_on_unknown_devices_cannot_delay_the_owners_known_device` |
| Guess an SMS code | 5 attempts per code, then it is burned | `test_five_wrong_codes_burn_the_code` |
| Read SMS codes from the database | Stored as a keyed HMAC, erased from the outbox once sent | `test_code_is_stored_only_as_an_hmac_and_erased_from_the_outbox_once_sent` |
| Make the site pay for texts to thousands of numbers (SMS pumping) | An hourly budget of codes for the whole site, checked before the number is looked up | `test_codes_pause_for_everyone_when_the_site_budget_is_spent` |
| Replay a two-step code | Each code is accepted once, by a conditional update | `test_a_used_code_cannot_be_replayed` |
| Use a stolen refresh token | Rotation on every use; presenting an old one ends every session of the account | `test_reuse_after_the_grace_window_revokes_the_whole_family` |
| … without logging out a citizen on a flaky connection | A 60-second grace window returns the same successor | `test_a_retry_within_the_grace_window_gets_the_same_successor` |
| Hash passwords on the main pool, to starve logged-in users | Nginx sends every hashing route to `api-auth`; a test fails if a route hashes on the wrong pool | `test_bulkhead_guard_catches_hashing_on_the_main_pool` |
| Submit twice through a retried request | `Idempotency-Key`; a reused key with a different body is refused | `test_the_same_key_returns_the_same_answer_and_submits_once`, `test_a_key_reused_with_a_different_body_is_refused` |
| Upload malware disguised as a PDF | ClamAV scans before the type is read from the bytes; nothing is downloadable until both pass | `test_the_scanner_rejects_malware_even_disguised_as_a_pdf` |
| Tamper with a signed token or the stored two-step secret | Signatures are checked; the encrypted secret detects tampering | `test_tampered_payload_is_refused`, `test_secret_encryption_round_trip_and_tamper_detection` |
| Two officers claim the same request | `SELECT … FOR UPDATE SKIP LOCKED` | `test_parallel_officers_each_get_a_different_request` |

What the tests do not cover is in [limitations](limitations.md#3-security-where-the-defences-stop): a distributed login flood, a paused SMS budget, the locks' GOVERNANCE mode, secrets on the server, and the lack of an outside security review.

---

## 12. What testing against the real thing corrected

Five defects passed every automated test and were found only by running against the real component. Each is now covered by a test or a check in CI.

| Found by | Defect | Fix |
|---|---|---|
| The chaos run, against a stopped broker | Each submission waited ~4 s per message for the dead broker; p95 11.7 s | Circuit breaker, 1 s connection timeout ([Q3](#5-q3-does-a-dead-task-broker-take-submissions-down-with-it)) |
| Real ClamAV in CI | Real ClamAV finds the EICAR test file only at the start of a file; our stand-in found it anywhere | The stand-in matches ClamAV, and the scan runs before the type check |
| Browser tests | The web app signed people out when the server answered "slow down" (429) | It retries; only a real 401 ends a session |
| The first email to a real inbox | Its link pointed at `localhost` | Production derives links from its domain and refuses to start otherwise |
| The first backup to real S3 | WAL-G hung: the PostgreSQL image had no CA certificates, so TLS to S3 never verified | CA certificates in the image; a CI step checks the image can verify an HTTPS bucket |

A sixth kind of finding came from walking each role's sign-up by hand. The demo's phone error gave as its example a real number that the demo refuses; the SMS language ignored the site's language; a new officer was sent a bare code and no idea what to do with it. None was a crash, and no test could have seen them. All are fixed and now tested.

---

## 13. Reproducing every number

| Number | Command |
|---|---|
| Test counts, coverage, suite time | `docker build --target test -t grs-app:test .`, then the `docker run … grs-app:test` line in the [README](../README.md#on-your-machine), with `pytest --cov=apps --cov=config` |
| Browser tests | `cd web && npx playwright test` |
| Load, chaos, edge | [loadtest/README.md](../loadtest/README.md) |
| Restore and point-in-time recovery | `deploy/scripts/restore-check.sh`, `deploy/scripts/pitr-check.sh` |
| Password hash cost | `docker run --rm --cpus 1 -v "$PWD/tools:/tools:ro" --entrypoint python grs-app:test /tools/bench_password_hash.py` |
| Check digits | `docker run --rm -v "$PWD:/w" -w /w python:3.12-slim python tools/bench_check_digit.py` |
| Page weight | `cd web && npm run build && cd .. && python tools/measure_page_weight.py` |

---

## 14. Decisions and the evidence behind them

Each decision record lists the alternatives it rejected. This table puts beside each decision the evidence, in this document or in the tests, that supports it.

| # | Decision | Main alternative rejected | Deciding reason | Evidence |
|---|---|---|---|---|
| [1](decisions/0001-postgresql-enforces-the-rules.md) | PostgreSQL enforces the rules | Validation in Django only | A bug or a shell session cannot write an illegal row | Q1: illegal rows refused by the database |
| [2](decisions/0002-notifications-through-an-outbox.md) | Notifications through an outbox table | Enqueue a task after commit, and nothing else | A lost task is a lost message | Q3: 401 of 401 delivered after a broker outage |
| [3](decisions/0003-officers-take-the-next-request.md) | Officers take the next request | A list to pick from | Choosing is where favours and cherry-picking happen | `test_parallel_officers_each_get_a_different_request` |
| [4](decisions/0004-two-redis-instances.md) | Two Redis instances | One Redis for queue and cache | A full cache must never evict queued work | Q3; limits fail open when the cache is down |
| [5](decisions/0005-password-hashing-bulkhead.md) | Password hashing on its own pool | A faster hash | The slowness is the protection | Q2: browsing stayed under 1 s at p95 through the login burst; Q8 |
| [6](decisions/0006-hash-chained-audit-log.md) | Hash-chained audit log, anchors off the host | Trust grants and triggers alone | Whoever controls the database controls an unchained log | Q5: every tamper attempt caught |
| [7](decisions/0007-uploads-go-straight-to-storage.md) | Files go straight to storage, checked after | Upload through the API | A slow upload on 2G holds a worker for minutes | Scanner tests; ClamAV in CI |
| [8](decisions/0008-one-server-with-compose.md) | One server with Compose | Kubernetes | One part-time operator | Q2: one server carries 70–85 req/s |
| [9](decisions/0009-static-web-app.md) | Static web app from Nginx | A Node server | Nothing to run, cached forever | Q7: later pages 2–10 KB; the first visit is heavy |
| [10](decisions/0010-alerts-from-the-edge-log.md) | Service levels from Nginx's log | Prometheus and Grafana | Enough signal for one operator, no extra stack | Monitor tests |
| [11](decisions/0011-continuous-backups-off-the-server.md) | Continuous WAL archiving, restore drilled nightly | Nightly `pg_dump` only | A day of loss is too much; an untested backup is a hope | Q5: at most 60 s lost; PITR in 7 s |
| [12](decisions/0012-texts-carry-no-personal-data.md) | Texts carry no personal data | The reason in the text | Gateways and carriers are outside the office's control | Payload tests |
| [13](decisions/0013-a-phone-number-is-the-account.md) | A phone number is the account | National ID as the account | Everyone has a phone; the registry is an integration | Q9: enumeration and SMS-pumping tests |
| [14](decisions/0014-sessions-follow-the-device.md) | Session length follows the device | One lifetime for everyone | Shared computers are the default | Session and grace-window tests |
| [15](decisions/0015-tracking-numbers-are-read-aloud.md) | Damm check digit | Luhn; Verhoeff | Every single error and neighbour swap caught; the simplest | Q6, which also corrects its note on Verhoeff |
| [16](decisions/0016-every-statistic-has-a-counterweight.md) | Every statistic beside its counterweight | Headline numbers only | A published number becomes a target | Statistics tests |
| [17](decisions/0017-staff-access-is-visible.md) | Every staff look recorded, visible to the citizen | Log changes only | Curiosity is the most common privacy leak | Access-log tests |
| [18](decisions/0018-email-reaches-real-inboxes.md) | Real email through a relay, capped | One public inbox | Verification must reach the owner and no one else | Email tests; the `localhost` link found live |

---

## 15. Threats to validity

Beyond those listed under each question:

**Internal validity** (did we measure what we think we did?). Load and chaos numbers were taken with the load generator on the machine under test, one run each. Laptop timings ran under Docker Desktop on Windows, inside a virtual machine, and are indicative rather than absolute.

**External validity** (does it hold elsewhere?). All data is synthetic. Every person in the [problem](problem.md) is an assumption, not a finding from interviews. The workload, the error classes and the network speeds are models. The live server is in Mumbai, not in Bangladesh.

**Construct validity** (do the measures mean what we say?). "No errors under load" counts HTTP errors, not whether a citizen would put up with 8 seconds. Line coverage counts executed lines, not checked behaviour. "The edge limit works" is shown for one address, not many.

---

## 16. Summary

| Claim | Held? |
|---|---|
| The rules are enforced, and illegal states are refused by the database itself | **Yes**: 1,112 tests, 96% of lines, every cell of the transition matrix |
| One server carries a morning peak and degrades without failing | **Yes, up to 70–85 req/s**; no errors at twice that, but p95 of 8–11 s |
| A broker outage loses nothing and is invisible to users | **Yes**, after a fix the chaos run forced |
| One address cannot flood the login | **Yes**, within 2 requests of the configured limit. A botnet can; that is a stated limitation |
| At most a minute of data is lost with the server, and the restore is proven nightly | **Yes**, at demo size |
| History cannot be rewritten unnoticed | **Yes**, against every tamper test; the demo's locks are GOVERNANCE mode |
| A mistyped tracking number never opens another request | **Yes** for single errors and neighbour swaps (100%); about 90% for the rarer mistakes |
| The app works well on 2G | **No** for the first visit (about 16 s of transfer); yes for later pages |
