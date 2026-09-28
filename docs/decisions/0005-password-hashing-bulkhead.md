# 5. Password hashing runs on its own worker pool

**Status:** accepted

## Context

Passwords are hashed with Argon2id, which is slow on purpose. When offices open, many people log in at once. If hashing shares workers with the rest of the API, a login rush (or an attack on the login endpoint) occupies every worker and people already logged in cannot load their requests.

## Decision

The same image runs twice: `api` for general traffic and `api-auth` for every route that hashes a password (login, register, password set and reset, two-step verify). Nginx routes by path. A test runs during the whole suite and fails if any request hashes a password on a path Nginx does not send to `api-auth`, so a new endpoint cannot quietly break the split.

## Consequences

- A login surge queues on its own pool. In the live load test at 15 logins a second, the median login took 58 ms and the median page 15 ms; on two shared vCPUs the pools still compete for CPU, so separate hosts are the next step at higher load.
- Two worker pools to size instead of one.
- The route list exists in two places (Nginx and the code). The test keeps them in step.
