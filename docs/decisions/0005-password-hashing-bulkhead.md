# 5. Password hashing runs on its own worker pool

**Status:** accepted

## Context

Passwords are hashed with Argon2id, which is slow on purpose. When offices open, many people log in at once. If hashing shares workers with the rest of the API, a login rush (or an attack on the login endpoint) occupies every worker and people already logged in cannot load their requests.

## Decision

The same image runs twice: `api` for general traffic and `api-auth` for every route that hashes a password (login, register, password set and reset, two-step verify). Nginx routes by path. A test runs during the whole suite and fails if any request hashes a password on a path Nginx does not send to `api-auth`, so a new endpoint cannot quietly break the split.

## Alternatives considered

- **A faster hash** (fewer Argon2 iterations, or bcrypt at a low cost). Buys throughput by making every stolen hash cheaper to crack. The slowness is the protection.
- **Rate-limit logins harder.** Stops an attacker; does nothing for the real officers and citizens all logging in at 9 a.m.
- **Async workers.** Hashing is CPU work; an event loop waits on it just the same.

## Consequences

- A login surge queues on its own pool. In the live load test at 15 logins a second, the median login took 58 ms and the median page 15 ms; on two shared vCPUs the pools still compete for CPU, so separate hosts are the next step at higher load.
- Two worker pools to size instead of one.
- The route list exists in two places (Nginx and the code). The test keeps them in step.

## What this does not stop

Slow hashing can be turned against us: every login attempt costs about 23 ms of CPU, so a flood of attempts is a cheap way to spend ours. Three things keep that cost down.

- Nginx allows each address 10 login attempts a second, and refuses the rest before any Python runs.
- After five failures an account (per device) waits 1, 2, 4, 8, then 15 minutes, and the wait is checked before the password is hashed: a delayed attempt costs no CPU.
- Whatever gets through lands on this pool alone.

A botnet gets past the first two. From thousands of addresses, each under its limit, trying a different phone number each time, no account builds up a delay and every attempt is hashed, including attempts on numbers with no account, which are hashed on purpose so that timing does not reveal who is registered. Two workers at 23 ms a hash top out near 85 attempts a second (a calculation, not a measurement); above that, logging in slows or fails for everyone until the flood stops. People already logged in are not affected.

The per-address limit is not tightened to close this, because thousands of real phones share one address behind a mobile operator: a tight limit would lock out a district before it slowed a botnet. What closes it is filtering in front of the server (a DDoS service such as Cloudflare or AWS Shield), and a challenge on the login form that appears only while a flood is under way. Neither is in v1: they need a provider account and a public launch to be worth their cost.

## What would change this

Load where the two pools compete for the same CPUs: the next step is `api-auth` on its own host, which needs only a change to Nginx's upstream.
