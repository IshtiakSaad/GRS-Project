from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from tests import factories as f

pytestmark = pytest.mark.django_db


def _partition_of(table, pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT tableoid::regclass::text FROM {table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


def _audit(created_at=None):
    fields = {"action": "x", "target_type": "t"}
    if created_at:
        fields["created_at"] = created_at
    return AuditLog.objects.create(**fields)


def test_current_rows_land_in_this_years_partition():
    row = _audit()
    assert _partition_of("audit_log", row.pk) == f"audit_log_{timezone.now().year}"


def test_notifications_are_partitioned_by_month():
    row = Notification.objects.create(
        recipient=f.citizen(), channel="SMS", kind="STATUS", template="t"
    )
    assert _partition_of("notification", row.pk) == timezone.now().strftime("notification_%Y_%m")


def test_far_future_rows_still_insert_and_raise_the_alert():
    """If the partition job dies, inserts keep working; the DEFAULT partition catches them."""
    row = _audit(created_at=datetime(2061, 1, 1, tzinfo=UTC))
    assert _partition_of("audit_log", row.pk) == "audit_log_default"
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name, has_rows FROM default_partitions_in_use()")
        in_use = dict(cursor.fetchall())
    assert in_use["audit_log"] is True
    assert in_use["request_event"] is False


def test_ensure_partitions_is_idempotent():
    with connection.cursor() as cursor:
        cursor.execute("SELECT ensure_partitions()")
        assert cursor.fetchone()[0] == 0


def test_partitions_are_made_well_ahead():
    """Yearly tables three years ahead, notifications two years ahead."""
    year = timezone.now().year
    ahead = (timezone.now().replace(day=1) + timedelta(days=24 * 31)).strftime("%Y_%m")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_class WHERE relname = ANY(%s)",
            [[f"audit_log_{year + 3}", f"request_event_{year + 3}", f"notification_{ahead}"]],
        )
        assert cursor.fetchone()[0] == 3


def test_partitioned_tables_have_composite_keys_and_range_partitioning():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, pg_get_partkeydef(c.oid), pg_get_constraintdef(con.oid)
            FROM pg_class c
            JOIN pg_constraint con ON con.conrelid = c.oid AND con.contype = 'p'
            WHERE c.relkind = 'p' ORDER BY 1
            """
        )
        rows = cursor.fetchall()
    assert [r[0] for r in rows] == [
        "access_event",
        "access_event_item",
        "audit_log",
        "notification",
        "request_event",
    ]
    for _, partkey, pk in rows:
        assert partkey == "RANGE (created_at)"
        assert pk == "PRIMARY KEY (id, created_at)"
