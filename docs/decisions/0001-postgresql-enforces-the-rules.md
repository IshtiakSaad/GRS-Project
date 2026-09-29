# 1. PostgreSQL enforces the rules, not only the application

**Status:** accepted

## Context

A request's status decides which other columns must be set: a resolved request needs a resolution note, an assigned one needs an officer, a rejected one needs a reason. The audit log must never change. If these rules live only in Python, any path that skips the service layer (a data fix, a shell session, a future second service, a bug) can write a row the rest of the system cannot interpret.

## Decision

Every rule that can be expressed as a constraint is one: `CHECK` constraints for status and the columns it requires, partial unique indexes (one open SLA pause per request), triggers that make log tables append-only, and separate database roles for migrations, the API and the workers, each with only the grants it needs and its own statement timeout. The application still validates first, to give users clear errors.

## Alternatives considered

- **Validate in Django only** (model `clean()`, serializers). The usual choice, and it protects exactly one path into the database. A management command, a migration's data step or a hurried fix in `psql` walks straight past it.
- **Put all logic in the database** (stored procedures for every transition). The rules could never be bypassed, but they would be hard to test, review and read, and errors would reach users as SQL messages. We put in the database what is a *fact about valid data* (which columns a status requires), and kept in Python what is a *decision* (who may do what, and when).
- **One database role for everything.** Simpler to configure, and it means the web process could `DROP TABLE` or rewrite the audit log if it were ever tricked into running the wrong query.

## Consequences

- A bug in Python produces an error, not a corrupt row.
- Every constraint has a test that inserts the illegal row directly and expects PostgreSQL to refuse it.
- Schema changes need more care: a new status means a migration that updates constraints.
- The design is tied to PostgreSQL. That was never going to change.

## What would change this

If new states or offices with their own rules started arriving every month, hand-written `CHECK` constraints would drift from the Python transition table. The constraints would then be generated from that same table, so the two could not disagree.
