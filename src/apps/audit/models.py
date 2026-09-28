"""Who did what, and who looked at what.

Log tables are partitioned by year and append-only (trigger + grants). They reference accounts
and requests by id without foreign-key constraints: the log must never depend on, or block
changes to, the rows it describes. The database key of each partitioned table is
(id, created_at); see migration 0002.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThanOrEqual

from apps.common.db import created_at_field, in_choices

GENESIS_HASH = "0" * 64


def _soft_fk(to, **kwargs):
    return models.ForeignKey(
        to,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_index=False,
        db_constraint=False,
        **kwargs,
    )


class AuditLog(models.Model):
    """Every state change and administrative action.

    Rows are sealed in order by a single background job into a SHA-256 hash chain
    (seal_seq, prev_hash, row_hash). Sealing is the only UPDATE the trigger allows, once per row.
    """

    actor = _soft_fk(settings.AUTH_USER_MODEL, null=True, blank=True)
    actor_role = models.CharField(max_length=8, null=True, blank=True)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=32)
    target_id = models.BigIntegerField(null=True, blank=True)
    request = _soft_fk("service_requests.ServiceRequest", null=True, blank=True)
    data = models.JSONField(default=dict)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_uid = models.CharField(max_length=64, null=True, blank=True)  # X-Request-ID
    created_at = created_at_field()

    seal_seq = models.BigIntegerField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64, null=True, blank=True)
    row_hash = models.CharField(max_length=64, null=True, blank=True)
    sealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_log"
        constraints = [
            # Seal columns are set together or not at all.
            models.CheckConstraint(
                condition=Q(
                    seal_seq__isnull=True,
                    prev_hash__isnull=True,
                    row_hash__isnull=True,
                    sealed_at__isnull=True,
                )
                | Q(
                    seal_seq__isnull=False,
                    prev_hash__isnull=False,
                    row_hash__isnull=False,
                    sealed_at__isnull=False,
                ),
                name="audit_log_seal_complete",
            ),
        ]
        indexes = [
            models.Index(
                fields=["id"], condition=Q(sealed_at__isnull=True), name="audit_log_unsealed_idx"
            ),  # the sealer's work queue
            models.Index(
                fields=["target_type", "target_id"], name="audit_log_target_idx"
            ),  # history of one object
            models.Index(fields=["request", "created_at"], name="audit_log_request_idx"),
            models.Index(fields=["seal_seq"], name="audit_log_seal_seq_idx"),  # chain verification
        ]


class AuditAnchor(models.Model):
    """A checkpoint of the hash chain, copied outside this database.

    Each sealing batch writes one anchor here and one object to a write-once (Object Lock)
    bucket on a separate storage host. Rewriting the audit log then requires rewriting the
    locked copies too, which the bucket refuses. Until the copy exists, stored_at is empty
    and the anchor is reported as pending.
    """

    first_seal_seq = models.BigIntegerField()
    last_seal_seq = models.BigIntegerField()
    last_row_hash = models.CharField(max_length=64)
    object_key = models.CharField(max_length=255, unique=True)
    object_version = models.CharField(max_length=128, null=True, blank=True)
    stored_at = models.DateTimeField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "audit_anchor"
        constraints = [
            models.CheckConstraint(
                condition=GreaterThanOrEqual(models.F("last_seal_seq"), models.F("first_seal_seq")),
                name="audit_anchor_range_valid",
            ),
            models.UniqueConstraint(fields=["last_seal_seq"], name="audit_anchor_last_seq_unique"),
        ]
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=Q(stored_at__isnull=True),
                name="audit_anchor_pending_idx",
            ),
        ]


class AccessKind(models.TextChoices):
    VIEW = "VIEW"
    UPDATE = "UPDATE"
    DOWNLOAD = "DOWNLOAD"
    LIST = "LIST"  # a list page; the requests shown are in AccessEventItem


class BreakGlassReason(models.TextChoices):
    SUPERVISOR_REVIEW = "SUPERVISOR_REVIEW"
    CITIZEN_COMPLAINT = "CITIZEN_COMPLAINT"
    AUDIT = "AUDIT"
    DATA_CORRECTION = "DATA_CORRECTION"
    OTHER = "OTHER"


class AccessEvent(models.Model):
    """A member of staff opened, changed, downloaded or listed citizen requests."""

    actor = _soft_fk(settings.AUTH_USER_MODEL)
    actor_role = models.CharField(max_length=8)
    actor_department_id = models.BigIntegerField(null=True, blank=True)  # "which office looked"
    kind = models.CharField(max_length=8, choices=AccessKind)
    request = _soft_fk("service_requests.ServiceRequest", null=True, blank=True)
    item_count = models.PositiveIntegerField(default=1)
    break_glass_reason = models.CharField(
        max_length=20, choices=BreakGlassReason, null=True, blank=True
    )
    break_glass_note = models.CharField(max_length=500, null=True, blank=True)
    request_uid = models.CharField(max_length=64, null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "access_event"
        constraints = [
            in_choices("kind", AccessKind, "access_event"),
            in_choices("break_glass_reason", BreakGlassReason, "access_event"),
            # A single-request event names its request; a list event names them in items.
            models.CheckConstraint(
                condition=Q(kind=AccessKind.LIST) | Q(request__isnull=False),
                name="access_event_request_named",
            ),
            models.CheckConstraint(
                condition=~Q(break_glass_reason=BreakGlassReason.OTHER)
                | Q(GreaterThanOrEqual(Length("break_glass_note"), 20)),
                name="access_event_other_reason_explained",
            ),
        ]
        indexes = [
            models.Index(fields=["request", "created_at"], name="access_event_request_idx"),
            models.Index(fields=["actor", "created_at"], name="access_event_actor_idx"),
        ]


class AccessEventItem(models.Model):
    """One row per request shown on a staff list page.

    A narrow table with a plain b-tree index scales better than an array column with a GIN
    index, which is expensive to maintain at tens of millions of rows a year. It answers
    "which staff lists showed my request?" with one index range scan.
    """

    event_id = models.BigIntegerField()
    request = _soft_fk("service_requests.ServiceRequest")
    created_at = models.DateTimeField()  # copied from the event: same partition, same pruning

    class Meta:
        db_table = "access_event_item"
        indexes = [models.Index(fields=["request", "created_at"], name="access_item_request_idx")]


class AlertStatus(models.TextChoices):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


class AccessAlert(models.Model):
    """Unusual staff access, e.g. far more requests viewed in an hour than colleagues view.

    Written by a detection job over access_event; reviewed by an administrator other than the
    person flagged. Bulk reading by an insider is visible here even when every single view was
    individually allowed.
    """

    actor = _soft_fk(settings.AUTH_USER_MODEL)
    rule = models.CharField(max_length=32)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    observed = models.PositiveIntegerField()
    threshold = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=AlertStatus, default=AlertStatus.OPEN)
    reviewed_by = _soft_fk(settings.AUTH_USER_MODEL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "access_alert"
        constraints = [
            in_choices("status", AlertStatus, "access_alert"),
            models.CheckConstraint(
                condition=Q(window_end__gt=models.F("window_start")),
                name="access_alert_window_valid",
            ),
            models.CheckConstraint(
                condition=Q(status=AlertStatus.OPEN)
                | Q(reviewed_by__isnull=False, reviewed_at__isnull=False),
                name="access_alert_reviewed_has_reviewer",
            ),
            # Nobody closes an alert about themselves.
            models.CheckConstraint(
                condition=Q(reviewed_by__isnull=True) | ~Q(reviewed_by=models.F("actor")),
                name="access_alert_no_self_review",
            ),
            models.UniqueConstraint(
                fields=["actor", "rule", "window_start"], name="access_alert_once_per_window"
            ),
        ]
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=Q(status=AlertStatus.OPEN),
                name="access_alert_open_idx",
            ),
        ]
