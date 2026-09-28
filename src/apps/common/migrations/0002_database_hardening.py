"""Privileges, append-only guards, tracking numbers and partition management.

Everything here is enforced by PostgreSQL itself, so it holds for every client: the API, a
background job, a future service, or an operator at a psql prompt.
"""

from django.db import migrations

# Run as grs_owner. A superuser would own the SECURITY DEFINER functions below and give them
# superuser rights, so refuse.
GUARD = """
DO $$
BEGIN
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run migrations as grs_owner, not as a superuser (%)', current_user;
  END IF;
END $$;
"""

PRIVILEGES = """
-- Tables created later by this role are reachable by the runtime roles automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO grs_api, grs_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO grs_api, grs_worker;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO grs_api, grs_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO grs_api, grs_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO grs_api, grs_worker;

-- Only migrations change migration history.
REVOKE INSERT, UPDATE, DELETE ON django_migrations FROM grs_api, grs_worker;

-- Log tables: insert and read only.
REVOKE UPDATE, DELETE ON request_event, access_event, access_event_item, audit_log
  FROM grs_api, grs_worker;
-- The sealer (worker) may fill in the seal columns, and nothing else.
GRANT UPDATE (seal_seq, prev_hash, row_hash, sealed_at) ON audit_log TO grs_worker;

-- Anchors are the worker's business only; it may record where the copy was stored.
REVOKE ALL ON audit_anchor FROM grs_api;
REVOKE UPDATE, DELETE ON audit_anchor FROM grs_worker;
GRANT UPDATE (object_version, stored_at) ON audit_anchor TO grs_worker;

-- Access alerts are raised by the worker and reviewed through the API; never deleted.
REVOKE DELETE ON access_alert FROM grs_api, grs_worker;
"""

TRIGGERS = """
-- Generic guard: the row may be inserted, never changed or removed.
CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: % refused', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER request_event_append_only BEFORE UPDATE OR DELETE ON request_event
  FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER access_event_append_only BEFORE UPDATE OR DELETE ON access_event
  FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER access_event_item_append_only BEFORE UPDATE OR DELETE ON access_event_item
  FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- Audit rows: never deleted. The one permitted update seals an unsealed row and touches only
-- the seal columns; every other column is compared generically, so new columns are covered.
CREATE FUNCTION audit_log_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  seal_cols text[] := ARRAY['seal_seq', 'prev_hash', 'row_hash', 'sealed_at'];
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'audit_log is append-only: DELETE refused'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.sealed_at IS NOT NULL THEN
    RAISE EXCEPTION 'audit_log row % is sealed and immutable', OLD.id
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.sealed_at IS NULL THEN
    RAISE EXCEPTION 'audit_log rows may only be updated to seal them'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (to_jsonb(NEW) - seal_cols) IS DISTINCT FROM (to_jsonb(OLD) - seal_cols) THEN
    RAISE EXCEPTION 'sealing may not change audit_log row % content', OLD.id
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER audit_log_guard BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_guard();

-- Anchors: recorded once, then only the storage receipt may be filled in, once.
CREATE FUNCTION audit_anchor_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.stored_at IS NOT NULL
     OR (to_jsonb(NEW) - ARRAY['object_version', 'stored_at'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['object_version', 'stored_at']) THEN
    RAISE EXCEPTION 'audit_anchor rows are immutable once stored'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER audit_anchor_guard BEFORE UPDATE OR DELETE ON audit_anchor
  FOR EACH ROW EXECUTE FUNCTION audit_anchor_guard();

-- Requests copy department_id from their category, so a category must never move.
CREATE FUNCTION category_department_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'category % cannot change department; deactivate it and create a new one',
    OLD.id USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER category_department_immutable BEFORE UPDATE OF department_id ON category
  FOR EACH ROW WHEN (OLD.department_id IS DISTINCT FROM NEW.department_id)
  EXECUTE FUNCTION category_department_immutable();
"""

TRACKING = """
-- The business year of a moment, in Bangladesh time: 00:30 on 1 January in Dhaka is the new
-- year even though it is still 31 December in UTC.
CREATE FUNCTION tracking_year(ts timestamptz) RETURNS int
  LANGUAGE sql STABLE PARALLEL SAFE  -- not IMMUTABLE: time-zone rules can change
  RETURN extract(year FROM ts AT TIME ZONE 'Asia/Dhaka')::int;

-- Next serial for a year. Sequences take no row lock, so submissions never queue behind a
-- counter. If the year's sequence is missing it is created on the spot, so 1 January can never
-- stop submissions. The yearly job and its alert remain as a second line.
CREATE FUNCTION next_tracking_serial(p_year int) RETURNS bigint
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  seq text := format('tracking_seq_%s', p_year);
BEGIN
  IF p_year < 2000 OR p_year > 2999 THEN
    RAISE EXCEPTION 'tracking year out of range: %', p_year;
  END IF;
  BEGIN
    RETURN nextval(seq::regclass);
  EXCEPTION WHEN undefined_table THEN
    BEGIN
      -- Eight digits of headroom: the number widens instead of failing past ten million.
      EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I MAXVALUE 99999999 NO CYCLE', seq);
    EXCEPTION WHEN unique_violation OR duplicate_table THEN
      NULL;  -- a concurrent submission created it first
    END;
    RETURN nextval(seq::regclass);
  END;
END $$;

REVOKE EXECUTE ON FUNCTION next_tracking_serial(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION next_tracking_serial(int), tracking_year(timestamptz)
  TO grs_api, grs_worker;

-- Pre-create this year and the next five.
DO $$
DECLARE y int;
BEGIN
  FOR y IN tracking_year(now()) .. tracking_year(now()) + 5 LOOP
    EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I MAXVALUE 99999999 NO CYCLE',
                   format('tracking_seq_%s', y));
  END LOOP;
END $$;
"""

PARTITIONS = """
-- Which tables are partitioned, how, and how far ahead partitions are made.
CREATE TABLE partition_policy (
  table_name text PRIMARY KEY,
  period text NOT NULL CHECK (period IN ('month', 'year')),
  premake int NOT NULL CHECK (premake BETWEEN 1 AND 60),
  storage_params text
);
REVOKE ALL ON partition_policy FROM grs_api, grs_worker;

INSERT INTO partition_policy VALUES
  ('notification',      'month', 24,
   'fillfactor = 80, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02'),
  ('request_event',     'year',  3, NULL),
  ('audit_log',         'year',  3, NULL),
  ('access_event',      'year',  3, NULL),
  ('access_event_item', 'year',  3, NULL);

-- Creates any missing partitions from the current period through `premake` periods ahead.
-- Idempotent; run by migration and daily by the worker. Partitions are not an API: runtime
-- roles reach rows only through the parent table, whose grants and triggers apply.
CREATE FUNCTION ensure_partitions() RETURNS int
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  p record;
  start_ts timestamptz;
  stop_ts timestamptz;
  part text;
  created int := 0;
BEGIN
  FOR p IN SELECT * FROM partition_policy ORDER BY table_name LOOP
    start_ts := date_trunc(p.period, now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    FOR i IN 0 .. p.premake LOOP
      stop_ts := start_ts + ('1 ' || p.period)::interval;
      part := p.table_name || '_' || to_char(start_ts AT TIME ZONE 'UTC',
                CASE p.period WHEN 'month' THEN 'YYYY_MM' ELSE 'YYYY' END);
      IF to_regclass(part) IS NULL THEN
        EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                       part, p.table_name, start_ts, stop_ts);
        EXECUTE format('REVOKE ALL ON %I FROM grs_api, grs_worker', part);
        IF p.storage_params IS NOT NULL THEN
          EXECUTE format('ALTER TABLE %I SET (%s)', part, p.storage_params);
        END IF;
        created := created + 1;
      END IF;
      start_ts := stop_ts;
    END LOOP;
  END LOOP;
  RETURN created;
END $$;

-- Rows in a DEFAULT partition mean the partition job fell behind. An alert, not an outage.
CREATE FUNCTION default_partitions_in_use()
  RETURNS TABLE (table_name text, has_rows boolean)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE p record; found boolean;
BEGIN
  FOR p IN SELECT pp.table_name FROM partition_policy pp ORDER BY 1 LOOP
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', p.table_name || '_default') INTO found;
    table_name := p.table_name;
    has_rows := found;
    RETURN NEXT;
  END LOOP;
END $$;

REVOKE EXECUTE ON FUNCTION ensure_partitions(), default_partitions_in_use() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ensure_partitions(), default_partitions_in_use() TO grs_worker;

-- DEFAULT partitions were created before these grants; runtime roles do not touch them directly.
REVOKE ALL ON notification_default, request_event_default, audit_log_default,
  access_event_default, access_event_item_default FROM grs_api, grs_worker;

SELECT ensure_partitions();
"""

STORAGE = """
-- Leave free space in each page so status updates can stay on the same page (HOT updates), and
-- vacuum update-heavy tables sooner than the 20% default.
ALTER TABLE service_request SET (fillfactor = 90, autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE refresh_session SET (fillfactor = 80, autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE login_throttle SET (fillfactor = 70, autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE idempotency_record SET (autovacuum_vacuum_scale_factor = 0.05);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0001_initial"),
        ("accounts", "0002_initial"),
        ("audit", "0001_initial"),
        ("collab", "0001_initial"),
        ("directory", "0001_initial"),
        ("notifications", "0001_initial"),
        ("service_requests", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(GUARD, migrations.RunSQL.noop),
        migrations.RunSQL(PRIVILEGES, migrations.RunSQL.noop),
        migrations.RunSQL(TRIGGERS, migrations.RunSQL.noop),
        migrations.RunSQL(TRACKING, migrations.RunSQL.noop),
        migrations.RunSQL(PARTITIONS, migrations.RunSQL.noop),
        migrations.RunSQL(STORAGE, migrations.RunSQL.noop),
    ]
