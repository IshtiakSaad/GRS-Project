"""Guards on the schema itself.

1. Every model change has a migration.
2. Migrations after the initial schema must be safe to run during peak hours: no operation that
   holds a long table lock while live traffic queues behind it.
3. Partitioned tables, created by custom SQL, still match their Django models.
"""

import io

import pytest
from django.apps import apps
from django.contrib.postgres.operations import AddIndexConcurrently
from django.core.management import call_command
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader
from django.db.models import CheckConstraint, UniqueConstraint

# The initial schema was created on empty tables, where locks cost nothing. Everything added
# after this list is checked.
BASELINE = {
    ("accounts", "0001_initial"),
    ("accounts", "0002_initial"),
    ("audit", "0001_initial"),
    ("collab", "0001_initial"),
    ("common", "0001_initial"),
    ("common", "0002_database_hardening"),
    ("directory", "0001_initial"),
    ("notifications", "0001_initial"),
    ("service_requests", "0001_initial"),
}
OUR_APPS = {
    "accounts",
    "audit",
    "collab",
    "common",
    "directory",
    "notifications",
    "service_requests",
}


def lock_risks(migration) -> list[str]:
    """Operations that block reads or writes on a live table, with the safe alternative.

    A migration that has been reviewed and is safe despite matching a rule sets
    `reviewed_lock_safe = "<reason>"`.
    """
    if getattr(migration, "reviewed_lock_safe", None):
        return []
    risks = []
    for op in migration.operations:
        name = type(op).__name__
        # The safe form is a subclass of the unsafe one: only the atomic flag tells them apart.
        if isinstance(op, AddIndexConcurrently) and not migration.atomic:
            continue
        if isinstance(op, migrations.AddIndex):
            risks.append(f"{name}: use AddIndexConcurrently in a non-atomic migration")
        elif isinstance(op, migrations.AddConstraint) and isinstance(
            op.constraint, CheckConstraint
        ):
            risks.append(f"{name}: add the CHECK as NOT VALID, then VALIDATE in a later step")
        elif isinstance(op, migrations.AddConstraint) and isinstance(
            op.constraint, UniqueConstraint
        ):
            risks.append(f"{name}: build the unique index CONCURRENTLY, then attach it")
        elif isinstance(op, migrations.AlterField):
            risks.append(f"{name}: may rewrite the table; review and mark reviewed_lock_safe")
        elif isinstance(op, (migrations.RemoveField, migrations.DeleteModel)):
            risks.append(f"{name}: expand/contract; stop using it in one release, drop it later")
        elif isinstance(op, migrations.RunSQL):
            sql = " ".join(op.sql if isinstance(op.sql, (list, tuple)) else [op.sql]).upper()
            if "CREATE INDEX" in sql and "CONCURRENTLY" not in sql:
                risks.append(f"{name}: CREATE INDEX without CONCURRENTLY")
    return risks


@pytest.mark.django_db
def test_no_model_change_is_missing_a_migration():
    out = io.StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)


def test_migrations_after_baseline_are_lock_safe():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    problems = {
        key: lock_risks(migration)
        for key, migration in loader.disk_migrations.items()
        if key[0] in OUR_APPS and key not in BASELINE
    }
    assert {k: v for k, v in problems.items() if v} == {}


def test_lock_rules_catch_an_unsafe_migration():
    """The guard itself works: a typical unsafe migration is flagged on every count."""
    from django.db import models

    class Unsafe(migrations.Migration):
        operations = [
            migrations.AddIndex("comment", models.Index(fields=["body"], name="x_idx")),
            migrations.AddConstraint(
                "comment", CheckConstraint(condition=models.Q(id__gt=0), name="x_chk")
            ),
            migrations.RunSQL("CREATE INDEX y_idx ON comment (body)"),
            migrations.RemoveField("comment", "is_internal"),
        ]

    assert len(lock_risks(Unsafe("0099_unsafe", "collab"))) == 4


def test_lock_rules_accept_an_index_built_concurrently():
    from django.db import models

    class Safe(migrations.Migration):
        atomic = False
        operations = [AddIndexConcurrently("comment", models.Index(fields=["body"], name="x_idx"))]

    assert lock_risks(Safe("0099_safe", "collab")) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "label",
    [
        "service_requests.RequestEvent",
        "notifications.Notification",
        "audit.AuditLog",
        "audit.AccessEvent",
        "audit.AccessEventItem",
    ],
)
def test_partitioned_table_matches_its_model(label):
    model = apps.get_model(label)
    expected = {f.column: f.null for f in model._meta.concrete_fields}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable = 'YES' FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            [model._meta.db_table],
        )
        actual = dict(cursor.fetchall())
    assert actual == expected
