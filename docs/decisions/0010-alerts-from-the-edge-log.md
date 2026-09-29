# 10. Service levels are measured from Nginx's log, and alerts go to a phone

**Status:** accepted

## Context

The targets are 99.5% of API requests succeeding each month and p95 under one second, and status messages delivered within 15 minutes. Nobody watches a dashboard at 3 a.m., so the system has to say when a target is at risk, and say nothing otherwise. A full metrics stack (Prometheus, Grafana, Alertmanager) would be three more services to run and secure on one small server.

## Decision

Nginx already logs every request as JSON. It writes the same lines to a shared file, and a `monitor` process folds them into per-minute counts (requests, 5xx, a latency histogram) and keeps six hours. Each minute it also checks readiness through the public address and TLS, the database, the oldest unsent message, uploads stuck before their scan, audit checkpoints not yet copied off the host, disk space and the certificate's expiry.

Availability alerts use multi-window burn rates: alert when the month's error budget would be spent in about two days (1 h window, confirmed by the last 5 minutes) or five days (6 h, confirmed by 30 minutes). A short burst does not wake anyone; a sustained problem does, and the alert clears once the short window recovers.

Alerts go to a private ntfy topic, which pushes them to a phone: once when a problem starts, every two hours while it lasts, and once when it clears. The monitor is its own process and does not use the broker or the workers, so it still reports when they are what failed. A scheduled GitHub Actions job checks the public address from outside, for the one failure the monitor cannot report: the server itself going dark.

## Consequences

- No new infrastructure: one more process from the same image, and one log file kept under 20 MB.
- The indicators are logged each minute as one JSON line (`docker compose logs monitor | grep sli`), which is the record; there are no graphs.
- The counts live in memory: a monitor restart forgets the last six hours, so slow-burn alerts need time to re-arm.
- The ntfy topic name is the only secret; anyone who has it can read the alerts. They carry no personal data.
