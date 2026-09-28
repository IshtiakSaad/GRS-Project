# 8. One server with Docker Compose, not Kubernetes

**Status:** accepted

## Context

The system needs a public demo that is cheap, reproducible and understandable by one person. Kubernetes or a set of managed services would add cost and moving parts without changing what the application does.

## Decision

The same `docker-compose.yml` runs on a laptop and, with `docker-compose.prod.yml`, on one server. Only Nginx publishes ports. Scripts in `deploy/scripts/` bootstrap the server, get certificates, and deploy: build, migrate, restart, then wait until `/health/ready` reports the new commit through Nginx and TLS, and redeploy the previous commit if it does not. A nightly job backs up the database and restores the backup into a scratch database to prove it works.

## Consequences

- One command stands up the whole system anywhere Docker runs. The live server and CI use the same images.
- One server is a single point of failure. The warm standby (opt-in) and nightly backups limit data loss; they do not give automatic failover.
- Rollback moves code, not the schema, so migrations must stay additive between releases.
- Every piece already talks over the network by name, so moving one to its own host is a configuration change.
