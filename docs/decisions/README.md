# Decisions

Short records of the choices that shape the system: the context, what was decided, and what it costs.

| # | Decision |
|---|---|
| 1 | [PostgreSQL enforces the rules, not only the application](0001-postgresql-enforces-the-rules.md) |
| 2 | [Notifications go through an outbox table](0002-notifications-through-an-outbox.md) |
| 3 | [Officers take the next request; they do not choose](0003-officers-take-the-next-request.md) |
| 4 | [Two Redis instances, split by how they may fail](0004-two-redis-instances.md) |
| 5 | [Password hashing runs on its own worker pool](0005-password-hashing-bulkhead.md) |
| 6 | [The audit log is append-only and hash-chained](0006-hash-chained-audit-log.md) |
| 7 | [Files go straight to object storage and are checked afterwards](0007-uploads-go-straight-to-storage.md) |
| 8 | [One server with Docker Compose, not Kubernetes](0008-one-server-with-compose.md) |
| 9 | [The web app is static files served by the same Nginx](0009-static-web-app.md) |
