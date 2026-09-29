# From finding to proof

Each row starts with something we found about the problem ([problem.md](problem.md)), follows it to what we decided, where that lives in the code, and ends at the thing that proves it holds. Test names are written to be read as sentences; every one below runs in CI on every push.

## The citizen's connection and device

| Finding | Decision | Code | Proof |
|---|---|---|---|
| On 3G the request often arrives and the response does not; the phone retries | Submission takes an `Idempotency-Key`; the same key returns the stored answer | `common/idempotency.py` | `test_the_same_key_returns_the_same_answer_and_submits_once`, `test_a_double_tap_with_one_key_submits_once` |
| A lost refresh response looks exactly like token theft | A 60-second grace window returns the same successor token | `accounts/sessions.py` | `test_a_retry_within_the_grace_window_gets_the_same_successor`, `test_reuse_after_the_grace_window_revokes_the_whole_family` |
| Many citizens file from shared computers | Short sessions unless the citizen says the phone is theirs ([decision 14](decisions/0014-sessions-follow-the-device.md)) | `accounts/sessions.py` | `test_citizen_sessions_are_short_on_shared_devices_unless_the_phone_is_theirs` |
| A slow upload would hold a web worker for minutes | Files go straight to storage by signed URL ([decision 7](decisions/0007-uploads-go-straight-to-storage.md)) | `collab/storage.py` | `test_upload_check_and_download`, `test_upload_links_work_while_storage_is_down` |
| Thousands of phones share one address behind carrier NAT | Generous per-address limits at Nginx; the real limits are per phone and per account | `deploy/nginx/grs/http.conf`, `common/ratelimit.py` | `test_login_is_limited_per_phone`, `test_submitting_is_limited_per_user`; the live edge check ([loadtest](../loadtest/README.md)) |

## Language and numbers

| Finding | Decision | Code | Proof |
|---|---|---|---|
| Tracking numbers are read aloud and copied by hand | Damm check digit, verified before any lookup ([decision 15](decisions/0015-tracking-numbers-are-read-aloud.md)) | `service_requests/tracking.py` | `test_every_single_digit_error_is_caught`, `test_every_adjacent_swap_is_caught` |
| Citizens type Bangla digits, spaces, no dashes | Input is normalised before it is checked | `common/text.py`, `common/phone.py` | `test_parse_accepts_bangla_digits_spaces_and_missing_dashes`, `test_demo_number_in_any_common_form` |
| The same Bangla word can be typed as different code points | NFC normalisation, keeping the joiners Bangla needs | `common/text.py` | `test_clean_text_makes_equal_bangla_equal`, `test_clean_text_drops_control_characters_but_keeps_bangla_joiners` |
| Messages must be in the citizen's language | Texts are Bangla first; each account keeps its language | `notifications/templates.py` | `test_messages_follow_the_language_the_citizen_registered_in` |

## The office

| Finding | Decision | Code | Proof |
|---|---|---|---|
| Officers who choose their work choose the easy and the familiar | The queue chooses: priority, deadline, age ([decision 3](decisions/0003-officers-take-the-next-request.md)) | `service_requests/services.py` | `test_the_queue_is_most_urgent_then_earliest_deadline_then_first_come`, `test_parallel_officers_each_get_a_different_request` |
| Asking for information stops the clock, and is the easiest way to look punctual | Two requests per cycle; a third needs an administrator | `service_requests/transitions.py` | `test_request_info_pauses_the_clock_and_asks_the_citizen`, `test_a_third_information_request_needs_an_administrator` |
| Rejecting near the deadline dodges it | Every late rejection is reviewed, plus 5% of resolutions | `service_requests/transitions.py` | `test_a_late_rejection_is_queued_for_review`, `test_resolutions_are_sampled`, `test_nobody_reviews_their_own_decision` |
| Closing a request is not the same as solving it | Citizens reopen within 30 days, twice | `service_requests/transitions.py` | `test_resolve_opens_the_reopen_window`, `test_reopen_limits` |
| Every published number becomes a target | Each statistic comes with its counterweights ([decision 16](decisions/0016-every-statistic-has-a-counterweight.md)) | `admin_api/stats.py` | `test_each_metric_comes_with_its_counter_metrics` |
| Deadlines are working days in Dhaka, with holidays and closures | A pure calendar; open deadlines recomputed when a holiday is added | `sla/calendar.py`, `sla/services.py` | `test_the_deadline_skips_holidays_and_suspensions`, `test_sla_calendar.py` |
| Late requests are forgotten unless someone is told | Flagged once per cycle; the officer and department administrators are told | `sla/overdue.py` | `test_an_overdue_request_is_flagged_and_staff_are_told`, `test_it_is_flagged_once_per_cycle` |

## Privacy and accountability

| Finding | Decision | Code | Proof |
|---|---|---|---|
| Texts pass through carriers and sit on shared phones | Tracking number and status only ([decision 12](decisions/0012-texts-carry-no-personal-data.md)) | `notifications/templates.py` | Payload assertions in `test_submit_numbers_times_and_announces_the_request` and `test_comments.py` |
| The common breach is staff looking up someone they know | Every staff look is recorded, list pages too ([decision 17](decisions/0017-staff-access-is-visible.md)) | `audit/access.py` | `test_every_staff_read_of_a_request_is_recorded`, `test_a_list_page_records_every_request_it_showed` |
| A name on screen exposes an officer to pressure | Citizens see office and role, never names | `audit/serializers.py`, `collab/serializers.py` | `test_the_citizen_sees_which_office_looked_never_who` |
| Supervisors and complaints need to cross departments | Break-glass with a reason, and its own report | `audit/views.py` | `test_an_officer_opens_a_request_outside_their_scope_with_a_reason`, `test_the_break_glass_report` |
| Whoever controls the database controls its log | Append-only, hash-chained, checkpoints locked off the server ([decision 6](decisions/0006-hash-chained-audit-log.md)) | `audit/sealing.py`, `audit/offsite.py` | `test_rewriting_the_database_and_its_anchors_is_caught_off_the_host`, `test_cutting_off_the_end_of_the_chain_is_caught` |
| A bug or a hurried fix can write a row the system cannot interpret | PostgreSQL enforces the rules ([decision 1](decisions/0001-postgresql-enforces-the-rules.md)) | migrations, `deploy/postgres/` | `tests/integration/db/`, `test_transition_matrix.py` (every state, action and role) |

## Attackers

| Finding | Decision | Code | Proof |
|---|---|---|---|
| A registration form can reveal who has an account | Same answer for existing numbers; the owner is warned | `accounts/services.py` | `test_existing_number_gets_the_same_answer_and_its_owner_is_warned`, `test_wrong_password_and_unknown_phone_look_identical` |
| A lockout lets anyone lock an officer out | A growing delay, never a lockout; known devices have their own counter | `accounts/throttle.py` | `test_five_failures_then_a_growing_delay`, `test_attacker_on_unknown_devices_cannot_delay_the_owners_known_device` |
| A 6-digit code can be guessed | 5 attempts, 10 minutes, a cooldown and an hourly cap | `accounts/otp.py` | `test_five_wrong_codes_burn_the_code`, `test_resend_has_a_cooldown_and_an_hourly_cap` |
| An administrator's password alone is not enough | TOTP on every admin session; a stolen token cannot enrol | `accounts/` | `test_admin_endpoints_need_a_two_step_session`, `test_a_stolen_access_token_cannot_enrol_two_step_login` |
| A file's name and label say nothing about its content | ClamAV scan and type read from the bytes before any download | `collab/verification.py`, `collab/scanning.py` | `test_the_scanner_rejects_malware_even_disguised_as_a_pdf`, `test_the_type_comes_from_the_bytes_not_the_label`; real ClamAV in CI (`test_clamd.py`) |

## When parts fail

| Finding | Decision | Code | Proof |
|---|---|---|---|
| A status change the citizen never hears about did not happen, for them | Notifications are written in the same transaction ([decision 2](decisions/0002-notifications-through-an-outbox.md)) | `notifications/` | `test_a_row_the_broker_lost_is_enqueued_again`; chaos run: broker stopped under load, **401 of 401** delivered |
| With the broker down, each web request waited on it (found by the chaos run) | A circuit breaker skips the broker for 30 s | `common/broker.py` | `test_after_a_failure_it_stops_trying_for_a_while`; submit p95 during the outage fell from 11.7 s to 99 ms in the same rehearsal, and was 32 ms on the live server |
| A crashed worker must not lose or double-send a message | Leases with expiry; a cap on attempts | `notifications/delivery.py`, `sweeper.py` | `test_a_dead_workers_lease_is_recovered_and_counted`, `test_a_message_that_keeps_killing_workers_stops_at_the_cap` |
| Everyone logs in at 9 a.m. | Password hashing on its own pool ([decision 5](decisions/0005-password-hashing-bulkhead.md)) | `deploy/nginx/`, `tests/conftest.py` | A guard in every test run fails if a hashing route is not sent to `api-auth`; live storm: 0 errors at 72 req/s |
| A cache outage must not stop citizens | Rate limits fail open ([decision 4](decisions/0004-two-redis-instances.md)) | `common/ratelimit.py` | `test_limits_fail_open_when_the_cache_is_down` |
| If the scanner is down, files must wait, not pass | Unverified files are retried, never approved | `collab/tasks.py` | `test_a_file_waits_while_the_scanner_is_down` |
| A backup that was never restored is a hope | A restore to a named moment, from the off-host bucket alone, every night and on every push ([decision 11](decisions/0011-continuous-backups-off-the-server.md)) | `deploy/scripts/pitr-check.sh` | CI `smoke` job; nightly on the live server (restored in 7 s, chain verified) |
| Nobody watches a dashboard at 3 a.m. | Burn-rate alerts to a phone ([decision 10](decisions/0010-alerts-from-the-edge-log.md)) | `apps/monitoring/` | `test_monitoring.py`, `test_monitor.py` |
| A deploy can break the site | Wait for the new build to report healthy through TLS; roll back if not ([decision 8](decisions/0008-one-server-with-compose.md)) | `deploy/scripts/deploy.sh` | CI `smoke` job checks the served build is the one just built |
