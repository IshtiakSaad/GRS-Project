-- Cluster roles and database ownership. Run once, as the bootstrap superuser, on a new cluster.
-- Variables: owner_pw, api_pw, worker_pw, replicator_pw, db, bootstrap_user (psql -v name=value)
--
-- Each service connects as its own role. Timeouts live on the roles, so the database enforces
-- them whatever the client does.

\set ON_ERROR_STOP on

-- Runs migrations and owns every object. No statement timeout (concurrent index builds are
-- long); a short lock timeout so a migration never queues live traffic behind its lock.
CREATE ROLE grs_owner LOGIN PASSWORD :'owner_pw' CONNECTION LIMIT 5;
ALTER ROLE grs_owner SET lock_timeout = '3s';
ALTER ROLE grs_owner SET statement_timeout = 0;

-- The API. Bottom of the timeout ladder: statement 5 s < gunicorn 15 s < nginx 20 s.
-- A crashed request holding a lock is cut off after 10 s idle in a transaction.
CREATE ROLE grs_api LOGIN PASSWORD :'api_pw' CONNECTION LIMIT 30;
ALTER ROLE grs_api SET statement_timeout = '5s';
ALTER ROLE grs_api SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE grs_api SET lock_timeout = '2s';

-- Background jobs: longer statements (batched), same protection against stuck transactions.
CREATE ROLE grs_worker LOGIN PASSWORD :'worker_pw' CONNECTION LIMIT 10;
ALTER ROLE grs_worker SET statement_timeout = '60s';
ALTER ROLE grs_worker SET idle_in_transaction_session_timeout = '60s';

-- Streams WAL to the standby. Replication only: it cannot read tables through SQL.
CREATE ROLE grs_replicator LOGIN REPLICATION PASSWORD :'replicator_pw' CONNECTION LIMIT 3;

-- The owner may assume the runtime roles, so tests can check what each role is allowed to do.
GRANT grs_api, grs_worker TO grs_owner;

-- Superuser sessions are rare and powerful: log everything they do. Personal operator logins
-- get the same setting when they are created (see docs/runbook.md).
ALTER ROLE :"bootstrap_user" SET pgaudit.log = 'all';

-- PostgreSQL 15+: the public schema belongs to the database owner and PUBLIC cannot create in it.
ALTER DATABASE :"db" OWNER TO grs_owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO grs_api, grs_worker;

\connect :"db"
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pgaudit;
