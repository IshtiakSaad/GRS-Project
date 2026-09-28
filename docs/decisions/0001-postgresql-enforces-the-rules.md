# 1. PostgreSQL enforces the rules, not only the application

**Status:** accepted

## Context

A request's status decides which other columns must be set: a resolved request needs a resolution note, an assigned one needs an officer, a rejected one needs a reason. The audit log must never change. If these rules live only in Python, any path that skips the service layer (a data fix, a shell session, a future second service, a bug) can write a row the rest of the system cannot interpret.

## Decision

Every rule that can be expressed as a constraint is one: `CHECK` constraints for status and the columns it requires, partial unique indexes (one open SLA pause per request), triggers that make log tables append-only, and separate database roles for migrations, the API and the workers, each with only the grants it needs and its own statement timeout. The application still validates first, to give users clear errors.

## Consequences

- A bug in Python produces an error, not a corrupt row.
- Every constraint has a test that inserts the illegal row directly and expects PostgreSQL to refuse it.
- Schema changes need more care: a new status means a migration that updates constraints.
- The design is tied to PostgreSQL. That was never going to change.
