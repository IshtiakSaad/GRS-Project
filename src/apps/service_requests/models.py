from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.common.db import created_at_field, in_choices
from apps.common.ids import uuid7


class Status(models.TextChoices):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CITIZEN = "AWAITING_CITIZEN"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


OPEN_STATUSES = [Status.SUBMITTED, Status.ASSIGNED, Status.IN_PROGRESS, Status.AWAITING_CITIZEN]
WITH_OFFICER = [Status.ASSIGNED, Status.IN_PROGRESS, Status.AWAITING_CITIZEN]


class Priority(models.IntegerChoices):
    # Integers so that "priority DESC" sorts by urgency; text would sort alphabetically.
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class Relation(models.TextChoices):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    OTHER = "OTHER"


class RejectionReason(models.TextChoices):
    INCOMPLETE = "INCOMPLETE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    DUPLICATE = "DUPLICATE"
    WRONG_OFFICE = "WRONG_OFFICE"
    OTHER = "OTHER"


class ServiceRequest(models.Model):
    """A citizen's request. Not partitioned: hot queries use partial indexes over open requests,
    which stay small however much history accumulates (Phase 2 plan, DB-2)."""

    public_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    tracking_no = models.CharField(max_length=13, unique=True, null=True, blank=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requests",
        db_index=False,  # covered by sr_owner_created_idx
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,  # queried only for assisted submissions (partial index)
    )
    beneficiary_name = models.CharField(max_length=120, null=True, blank=True)
    beneficiary_relation = models.CharField(max_length=8, choices=Relation, null=True, blank=True)
    assisted = models.BooleanField(default=False)
    owner_confirmed_at = models.DateTimeField(null=True, blank=True)

    category = models.ForeignKey(
        "directory.Category", on_delete=models.PROTECT, related_name="+", db_index=False
    )
    # Denormalised from category for queue queries; safe because categories never move.
    department = models.ForeignKey(
        "directory.Department", on_delete=models.PROTECT, related_name="+", db_index=False
    )

    title = models.CharField(max_length=200)
    description = models.CharField(max_length=5000)
    content_hash = models.CharField(max_length=64, null=True, blank=True)

    priority = models.PositiveSmallIntegerField(choices=Priority, default=Priority.NORMAL)
    citizen_urgent = models.BooleanField(default=False)
    urgency_reason = models.CharField(max_length=500, null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,  # covered by sr_officer_workload_idx
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    reopen_deadline = models.DateTimeField(null=True, blank=True)

    resolution_note = models.CharField(max_length=5000, null=True, blank=True)
    rejection_reason_code = models.CharField(
        max_length=16, choices=RejectionReason, null=True, blank=True
    )
    rejection_note = models.CharField(max_length=5000, null=True, blank=True)

    info_request_count = models.PositiveSmallIntegerField(default=0)
    reopen_count = models.PositiveSmallIntegerField(default=0)
    reassignment_count = models.PositiveSmallIntegerField(default=0)

    version = models.PositiveIntegerField(default=1)  # ETag / If-Match
    created_at = created_at_field()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "service_request"
        constraints = [
            in_choices("status", Status, "service_request"),
            in_choices("beneficiary_relation", Relation, "service_request"),
            in_choices("rejection_reason_code", RejectionReason, "service_request"),
            models.CheckConstraint(
                condition=Q(priority__in=Priority.values), name="service_request_priority_valid"
            ),
            models.CheckConstraint(
                condition=Q(tracking_no__regex=r"^[0-9]{2}-[0-9]{7,8}-[0-9]$"),
                name="service_request_tracking_no_format",
            ),
            # Anything past DRAFT has been numbered, timestamped and given a deadline.
            models.CheckConstraint(
                condition=Q(status=Status.DRAFT)
                | Q(
                    tracking_no__isnull=False,
                    submitted_at__isnull=False,
                    due_at__isnull=False,
                ),
                name="service_request_submitted_complete",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=WITH_OFFICER) | Q(assigned_officer__isnull=False),
                name="service_request_assigned_has_officer",
            ),
            models.CheckConstraint(
                condition=~Q(status=Status.RESOLVED)
                | Q(resolution_note__isnull=False, resolved_at__isnull=False),
                name="service_request_resolved_has_note",
            ),
            models.CheckConstraint(
                condition=~Q(status=Status.REJECTED) | Q(rejection_reason_code__isnull=False),
                name="service_request_rejected_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(citizen_urgent=False) | Q(urgency_reason__isnull=False),
                name="service_request_urgent_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(assisted=False) | ~Q(submitted_by=F("owner")),
                name="service_request_assisted_by_other",
            ),
            models.CheckConstraint(
                condition=Q(beneficiary_name__isnull=True, beneficiary_relation__isnull=True)
                | Q(beneficiary_name__isnull=False, beneficiary_relation__isnull=False),
                name="service_request_beneficiary_complete",
            ),
            models.CheckConstraint(
                condition=Q(info_request_count__lte=3), name="service_request_info_requests_max"
            ),
            models.CheckConstraint(
                condition=Q(reopen_count__lte=2), name="service_request_reopens_max"
            ),
            models.CheckConstraint(
                condition=Q(due_at__isnull=True) | Q(due_at__gte=F("submitted_at")),
                name="service_request_due_after_submit",
            ),
        ]
        indexes = [
            # Each index serves one named query; every index taxes every write.
            models.Index(
                fields=["owner", "-created_at", "-id"], name="sr_owner_created_idx"
            ),  # citizen's own list
            models.Index(
                fields=["department", "-priority", "due_at", "submitted_at"],
                condition=Q(status=Status.SUBMITTED),
                name="sr_dept_queue_idx",
            ),  # claim-next queue
            models.Index(
                fields=["assigned_officer", "status"],
                condition=Q(status__in=WITH_OFFICER),
                name="sr_officer_workload_idx",
            ),  # officer's open work
            models.Index(
                fields=["due_at"], condition=Q(status__in=OPEN_STATUSES), name="sr_open_due_idx"
            ),  # overdue scan, SLA recompute
            models.Index(
                fields=["owner", "content_hash", "-submitted_at"], name="sr_duplicate_idx"
            ),  # possible-duplicate check
            models.Index(
                fields=["owner", "submitted_at"],
                condition=Q(assisted=True),
                name="sr_assisted_owner_idx",
            ),  # assisted anomaly: many names on one phone
            models.Index(
                fields=["submitted_by", "submitted_at"],
                condition=Q(assisted=True),
                name="sr_assisted_officer_idx",
            ),  # assisted anomaly: officer's unconfirmed ratio
            models.Index(
                fields=["department", "submitted_at"], name="sr_dept_submitted_idx"
            ),  # statistics by department and period
            models.Index(
                fields=["category", "submitted_at"], name="sr_category_submitted_idx"
            ),  # statistics by category and period
        ]

    def __str__(self):
        return self.tracking_no or str(self.public_id)


class PauseReason(models.TextChoices):
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    UNCLEAR_REQUEST = "UNCLEAR_REQUEST"
    VERIFICATION = "VERIFICATION"
    OTHER = "OTHER"


class SlaPause(models.Model):
    """Time spent waiting on the citizen; the deadline extends by these working days."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.PROTECT, related_name="pauses", db_index=False
    )
    reason_code = models.CharField(max_length=20, choices=PauseReason)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sla_pause"
        constraints = [
            in_choices("reason_code", PauseReason, "sla_pause"),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("started_at")),
                name="sla_pause_range_valid",
            ),
            models.UniqueConstraint(
                fields=["request"], condition=Q(ended_at__isnull=True), name="sla_pause_one_open"
            ),
        ]
        indexes = [models.Index(fields=["request", "started_at"], name="sla_pause_request_idx")]


class RequestEvent(models.Model):
    """The request's timeline. Append-only (trigger + grants). Partitioned by year; the database
    key is (id, created_at). See migration 0002."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.PROTECT, related_name="events", db_index=False
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
        db_constraint=False,  # the log must not depend on account rows
    )
    actor_role = models.CharField(max_length=8, null=True, blank=True)
    event_type = models.CharField(max_length=32)
    from_status = models.CharField(max_length=16, null=True, blank=True)
    to_status = models.CharField(max_length=16, null=True, blank=True)
    is_public = models.BooleanField(default=True)  # shown on the citizen's timeline
    data = models.JSONField(default=dict)
    created_at = created_at_field()

    class Meta:
        db_table = "request_event"
        indexes = [models.Index(fields=["request", "created_at"], name="request_event_request_idx")]
