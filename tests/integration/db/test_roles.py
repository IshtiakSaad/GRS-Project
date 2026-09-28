"""Each runtime role can do exactly what it needs, and PostgreSQL refuses the rest.

The connections log in as the real roles, so these tests see the same privileges and role
settings that production services get. Privilege checks happen when a statement is planned,
so `WHERE false` proves the right without touching data.
"""

import psycopg
import pytest

pytestmark = pytest.mark.django_db


def _denied(conn, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sql)


def _allowed(conn, sql):
    conn.execute(sql)


# --- timeouts live on the roles -----------------------------------------------------------


def test_api_role_has_the_bottom_of_the_timeout_ladder(as_api):
    settings = dict(
        as_api.execute(
            "SELECT name, setting FROM pg_settings WHERE name IN "
            "('statement_timeout', 'idle_in_transaction_session_timeout', 'lock_timeout')"
        ).fetchall()
    )
    assert settings == {
        "statement_timeout": "5000",
        "idle_in_transaction_session_timeout": "10000",
        "lock_timeout": "2000",
    }


def test_api_statement_timeout_actually_fires(as_api):
    with pytest.raises(psycopg.errors.QueryCanceled):
        as_api.execute("SELECT pg_sleep(6)")


def test_worker_role_allows_longer_batches(as_worker):
    value = as_worker.execute("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")
    assert value.fetchone()[0] == "60000"


# --- the API role ----------------------------------------------------------------------------


def test_api_writes_domain_tables(as_api):
    _allowed(as_api, "UPDATE service_request SET priority = 2 WHERE false")
    _allowed(as_api, "INSERT INTO comment SELECT * FROM comment WHERE false")


def test_api_cannot_rewrite_history(as_api):
    for table in ("audit_log", "request_event", "access_event", "access_event_item"):
        _allowed(as_api, f"INSERT INTO {table} SELECT * FROM {table} WHERE false")
        _denied(as_api, f"UPDATE {table} SET id = id WHERE false")
        _denied(as_api, f"DELETE FROM {table} WHERE false")


def test_api_cannot_reach_partitions_directly(as_api):
    _denied(as_api, "SELECT 1 FROM audit_log_default WHERE false")


def test_api_cannot_touch_anchors_or_migrations(as_api):
    _denied(as_api, "SELECT 1 FROM audit_anchor WHERE false")
    _denied(as_api, "DELETE FROM django_migrations WHERE false")
    _denied(as_api, "SELECT 1 FROM partition_policy WHERE false")


def test_api_cannot_change_the_schema(as_api):
    _denied(as_api, "CREATE TABLE intruder (id int)")
    _denied(as_api, "ALTER TABLE service_request ADD COLUMN intruder int")


def test_api_can_number_requests_but_not_manage_partitions(as_api):
    assert as_api.execute("SELECT next_tracking_serial(2026)").fetchone()[0] >= 1
    _denied(as_api, "SELECT ensure_partitions()")


# --- the worker role -------------------------------------------------------------------------


def test_worker_may_seal_but_not_edit_audit_rows(as_worker):
    _allowed(as_worker, "UPDATE audit_log SET sealed_at = now(), row_hash = 'x' WHERE false")
    _denied(as_worker, "UPDATE audit_log SET action = 'forged' WHERE false")
    _denied(as_worker, "DELETE FROM audit_log WHERE false")


def test_worker_may_record_anchor_receipts_only(as_worker):
    _allowed(as_worker, "INSERT INTO audit_anchor SELECT * FROM audit_anchor WHERE false")
    _allowed(as_worker, "UPDATE audit_anchor SET stored_at = now() WHERE false")
    _denied(as_worker, "UPDATE audit_anchor SET last_row_hash = 'x' WHERE false")
    _denied(as_worker, "DELETE FROM audit_anchor WHERE false")


def test_worker_manages_partitions(as_worker):
    assert as_worker.execute("SELECT ensure_partitions()").fetchone()[0] == 0  # already made
    rows = as_worker.execute("SELECT table_name FROM default_partitions_in_use()").fetchall()
    assert {r[0] for r in rows} == {
        "notification",
        "request_event",
        "audit_log",
        "access_event",
        "access_event_item",
    }


def test_nobody_deletes_access_alerts(as_api, as_worker):
    _denied(as_api, "DELETE FROM access_alert WHERE false")
    _denied(as_worker, "DELETE FROM access_alert WHERE false")
