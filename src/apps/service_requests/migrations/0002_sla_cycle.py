"""Start of the current SLA cycle, so a reopened request gets a fresh deadline without losing its
original submission time.

Lock-safe: the column is nullable (no rewrite); the CHECK is added NOT VALID (a brief lock, no
scan) and validated in its own transaction, which scans without blocking writes.
"""

from django.db import migrations, models

CONSTRAINT = "service_request_sla_started"


class Migration(migrations.Migration):
    atomic = False  # each statement commits on its own; VALIDATE must not run under the ADD lock

    dependencies = [
        ("service_requests", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="sla_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunSQL(
            "UPDATE service_request SET sla_started_at = submitted_at "
            "WHERE status <> 'DRAFT' AND sla_started_at IS NULL",
            migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="servicerequest",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            ("status", "DRAFT"), ("sla_started_at__isnull", False), _connector="OR"
                        ),
                        name=CONSTRAINT,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    f"ALTER TABLE service_request ADD CONSTRAINT {CONSTRAINT} "
                    "CHECK (status = 'DRAFT' OR sla_started_at IS NOT NULL) NOT VALID",
                    f"ALTER TABLE service_request DROP CONSTRAINT {CONSTRAINT}",
                ),
                migrations.RunSQL(
                    f"ALTER TABLE service_request VALIDATE CONSTRAINT {CONSTRAINT}",
                    migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
