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

One Ubuntu 24.04 server (2 vCPU, 4 GB is enough for the demo), DNS pointing two names at it: `<domain>` and `files.<domain>`, plus the records the email provider asks for (see [Email](#email)).

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

Two kinds, both checked every night at 02:00 Dhaka (cron from `bootstrap-server.sh`; log: `/var/log/grs-backup.log`):

- **Continuous, off the server.** PostgreSQL ships each WAL segment to the off-host bucket (`OFFSITE_S3_BUCKET`, Object Lock) at least once a minute, and `deploy/scripts/backup.sh` adds a base backup there nightly, keeping 7. `deploy/scripts/pitr-check.sh` then restores from the bucket alone, in a throwaway container, to a named point it has just marked, checks row counts and verifies the audit chain in the copy. CI runs the same drill on every push.
- **Logical, on the server.** `backup.sh` also writes a `pg_dump` to `/var/backups/grs` (7 days); `restore-check.sh` restores it into a scratch database and checks it.

The server reaches the bucket through its instance role (`grs-server`), which can add objects but not delete versions or change locks. Nothing to rotate; nothing stored on the server. To move a server from a stand-in bucket to the real one, set `OFFSITE_S3_BUCKET` and `OFFSITE_S3_REGION`, leave `OFFSITE_S3_ENDPOINT` and the two keys empty, restart `postgres`, `worker` and `offsite-init`, take a base backup (`backup.sh`), and run `pitr-check.sh` once by hand. Two things to expect:

- Containers reach the instance role through the metadata service one network hop further than the host, so the instance's metadata hop limit must be 2.
- Audit checkpoints copied to the old bucket are not in the new one, so `verify_audit` reports the chain broken at the first of them. That is the check working: it cannot tell a moved bucket from deleted evidence, and copying the old checkpoints across by hand is the rewrite it exists to catch. On the demo, `reset-demo.sh` starts a new chain; a real system should switch buckets only with the old one kept, never by copying.

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C exec -u postgres postgres bash /grs/wal-g.sh backup-list          # base backups
$C exec postgres psql -U postgres -c "SELECT * FROM pg_stat_archiver"   # WAL shipping
```

**Restore to a moment** (data was damaged at a known time, or the server is gone). On the new or cleaned server, with the same `.env`:

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
SYSID=<system identifier: the folder name under wal/ in the bucket>
$C stop api api-auth worker beat monitor postgres
$C run --rm --no-deps -e WALG_SYSTEM_ID=$SYSID --entrypoint bash postgres -c '
  pg_isready -q -h postgres && { echo "postgres is still running: stop it first" >&2; exit 1; }
  rm -rf /var/lib/postgresql/data/* && gosu postgres bash /grs/wal-g.sh backup-fetch "$PGDATA" LATEST &&
  gosu postgres touch "$PGDATA/recovery.signal" &&
  echo "restore_command = '"'"'bash /grs/wal-g.sh wal-fetch %f %p'"'"'" >> "$PGDATA/postgresql.auto.conf" &&
  echo "recovery_target_time = '"'"'2026-09-29 10:15:00+06'"'"'" >> "$PGDATA/postgresql.auto.conf"'
$C up -d postgres        # replays to the target, then pauses: check the data, then
$C exec postgres psql -U postgres -c "SELECT pg_wal_replay_resume()"
$C up -d && $C run --rm migrate python manage.py verify_audit
```

Leave out `recovery_target_time` to replay everything archived (the server was lost). Afterwards remove the recovery settings, or every later base backup carries them:

```bash
$C exec postgres psql -U postgres -c "ALTER SYSTEM RESET restore_command" -c "ALTER SYSTEM RESET recovery_target_time"
```

**From the dump instead** (quick, but only to last night):

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C stop api api-auth worker beat
$C exec -T postgres psql -U postgres -c "DROP DATABASE grs" -c "CREATE DATABASE grs OWNER grs_owner"
$C exec -T postgres pg_restore -U postgres -d grs --exit-on-error < /var/backups/grs/<file>.dump
$C up -d && $C run --rm migrate python manage.py verify_audit --restored-copy
```

## Audit checkpoints

`manage.py verify_audit` checks the audit chain against the locked copies in the off-host bucket (`anchors/<chain id>/`); it fails if the bucket cannot be read. `--local-only` checks against the database's own anchors (weaker: whoever can rewrite the rows can rewrite those too). `--restored-copy` is for a restored backup, which legitimately ends before the newest copies.

## Email

Email leaves through an SMTP relay that delivers to real inboxes; the demo uses Resend's free plan (100 emails a day). Production refuses to start with Mailpit as the relay, a `localhost` link, or a relay user without a key.

1. At the provider, add the sending domain (`<domain>`) and add the DNS records it lists (SPF, DKIM, and the bounce MX) at the registrar. Wait until the provider shows the domain verified.
2. Create an API key that can only send, and put it in the server's `.env` as `EMAIL_HOST_PASSWORD`. The other lines are written by `gen-env.sh`: `EMAIL_HOST=smtp.resend.com`, `EMAIL_PORT=465`, `EMAIL_USE_SSL=true`, `EMAIL_HOST_USER=resend`.
3. Deploy. Links in emails point at `https://<domain>` and the sender is `no-reply@<domain>` unless `PUBLIC_BASE_URL` or `DEFAULT_FROM_EMAIL` say otherwise.
4. Check: log in as a demo citizen, add your own address under Profile, and click the link that arrives.

A verification email goes to whatever address someone types, so it is the one message a stranger can aim at a third party. Each account gets three a day, and the whole site `EMAIL_VERIFY_DAILY_CAP` (60), below the provider's quota so a flood cannot use up what real users need. Both are counted from the outbox in PostgreSQL, so they hold when Redis is down. Status updates go only to addresses already verified.

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
