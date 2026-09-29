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

## First deploy (one server)

One Ubuntu 24.04 server (2 vCPU, 4 GB is enough for the demo), DNS pointing three names at it: `<domain>`, `files.<domain>`, `mail.<domain>`.

```bash
git clone https://github.com/IshtiakSaad/GRS-Project.git && cd GRS-Project
sudo bash deploy/scripts/bootstrap-server.sh     # Docker, swap, firewall, SSH keys only, cron
# log out and back in (docker group)
deploy/scripts/gen-env.sh <domain> <email>       # .env with fresh random secrets, mode 600
deploy/scripts/init-tls.sh                       # Let's Encrypt staging certificate first
deploy/scripts/init-tls.sh --live                # then the real one
deploy/scripts/deploy.sh                         # build, migrate, start, verify, roll back if not
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --no-deps api \
  python manage.py seed_demo                      # the public demo's synthetic data
```

Check: `https://<domain>/health/ready` answers `"status": "ok"` with the deployed commit as `build`.

## Deploying a change

```bash
deploy/scripts/deploy.sh            # latest main
deploy/scripts/deploy.sh v1.0.0     # a tag or commit
```

The script builds, runs migrations, restarts, and waits until `/health/ready` reports the new commit through Nginx and TLS. If it does not within two minutes, it redeploys the previous commit. A rollback moves code, not the schema, so migrations must stay additive: add columns and tables in one release, remove the old ones in a later one.

## Backups

Nightly at 02:00 Dhaka (cron from `bootstrap-server.sh`): `deploy/scripts/backup.sh` writes a `pg_dump` to `/var/backups/grs` and keeps 7 days, then `deploy/scripts/restore-check.sh` restores it into a scratch database, compares row counts and verifies the audit hash chain in the copy. Log: `/var/log/grs-backup.log`.

**Restore for real** (the service is down anyway, or data was damaged):

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C stop api api-auth worker beat
$C exec -T postgres psql -U postgres -c "DROP DATABASE grs" -c "CREATE DATABASE grs OWNER grs_owner"
$C exec -T postgres pg_restore -U postgres -d grs --exit-on-error < /var/backups/grs/<file>.dump
$C up -d && $C run --rm migrate python manage.py verify_audit
```

The backups sit on the same server: a lost disk loses them too. Copying them off the server (and continuous WAL archiving for point-in-time recovery) is on the roadmap.

## Alerts

The `monitor` service sends alerts to `NTFY_URL`, a private ntfy topic (`https://ntfy.sh/<long random name>`); subscribe to the same topic in the ntfy phone app. Set it in `.env` on the server, then:

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C up -d monitor
$C exec monitor python manage.py monitor --test-alert   # the phone should buzz
$C exec monitor python manage.py monitor --once         # every check, now
$C logs monitor | grep '"sli'                           # the indicators, one line a minute
```

For the outside check, set the repository variable `UPTIME_URL` (`https://<domain>/health/ready`) and the secret `NTFY_URL` in GitHub. Delete the variable when the server is retired, or the job will keep alerting.

## Public demo reset

Nightly at 03:00 Dhaka: `deploy/scripts/reset-demo.sh` deletes the database, stored files, queues and demo email, then migrates and reseeds. It refuses to run unless `DEMO_MODE=true`. Log: `/var/log/grs-reset.log`.
