# Runbook

Operational procedures. Each one says what to do, what to check, and what never to do.

## Database roles

| Role | Used by | Can |
|---|---|---|
| `postgres` | first start only, emergencies | everything; every statement is audit-logged |
| `grs_owner` | `migrate` | change the schema; 3 s lock timeout so a migration never queues live traffic |
| `grs_api` | `api`, `api-auth` | read and write domain tables; insert-only on log tables; 5 s statement timeout |
| `grs_worker` | `worker`, `beat` | as `grs_api`, plus sealing audit rows and managing partitions; 60 s timeout |
| `grs_replicator` | `postgres-standby` | stream WAL; cannot read tables |

Timeouts are set on the roles, so they apply to every client.

## Personal operator access

Nobody shares `postgres`. Each operator gets a personal login whose every statement is logged by pgaudit (only a superuser can turn this off):

```sql
CREATE ROLE ops_jdoe LOGIN PASSWORD '...' IN ROLE grs_worker;
ALTER ROLE ops_jdoe SET pgaudit.log = 'all';
ALTER ROLE ops_jdoe SET statement_timeout = '30s';
```

Database logs must be shipped to a separate host that operators cannot edit. Until that is in place, direct database access is logged but the log itself is not tamper-proof.

## Standby

Start a streaming read-only copy:

```bash
docker compose --profile standby up -d postgres-standby
```

Check it is streaming (on the primary):

```sql
SELECT client_addr, state, replay_lag FROM pg_stat_replication;
```

**Promote** only when the primary is confirmed lost, never automatically. Two people agree, and the decision is recorded:

1. Stop the primary completely so it cannot come back as a second writer.
2. `docker compose exec postgres-standby gosu postgres pg_ctl promote`
3. Point `OWNER_DATABASE_URL`, `API_DATABASE_URL` and `WORKER_DATABASE_URL` at the standby, restart the app services, check `/health/ready`.
4. Rebuild a new standby from the new primary.

A stopped standby holds WAL on the primary through its replication slot, capped at 4 GB (`max_slot_wal_keep_size`). If the standby is retired, drop the slot: `SELECT pg_drop_replication_slot('standby_1');`

## Partitions

Log tables are partitioned by time, with partitions created years ahead and a daily job that keeps it that way. Rows that arrive with no matching partition go to a `DEFAULT` partition, so writes never fail.

Check for fallen-behind partitions:

```sql
SELECT * FROM default_partitions_in_use() WHERE has_rows;
```

If a table appears: run `SELECT ensure_partitions();` as `grs_worker`, then open an incident to move the rows out of the `DEFAULT` partition during a quiet window. Never drop a log partition, except `notification` partitions past their retention.

## Tracking numbers

Each year has its own sequence (`tracking_seq_2026`, ...), created six years ahead. A missing year is also created automatically on the first submission of that year. The number widens from seven to eight digits instead of failing past ten million requests in a year.

## First administrator

No API can create an administrator. On the host:

```bash
docker compose run --rm migrate python manage.py createadmin --phone 01000000001 --name "Admin Name"
```

The password is read from the terminal, never from the command line. The command prints the
authenticator (TOTP) link and ten recovery codes once; store the codes offline.

## Rotating keys

| Key | How to rotate | Effect |
|---|---|---|
| `JWT_SIGNING_KEYS` / `JWT_ACTIVE_KID` | Add the new key, make it active, deploy; remove the old key after 10 minutes | None: old access tokens verify until they expire |
| `FIELD_ENCRYPTION_KEYS` | Put the new key first, keep the old one after it, deploy | None: the first key encrypts, every key decrypts |
| `DJANGO_SECRET_KEY` | Move the old value to `DJANGO_SECRET_KEY_FALLBACKS`, set the new one | SMS codes in flight (10 min) and the 60 s refresh retry window stop matching; device and email tokens keep working through the fallback. Recovery codes are unaffected (hashed with Argon2) |

Production settings refuse to start with the placeholder keys from `.env.example`.
