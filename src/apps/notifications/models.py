from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

from apps.common.db import created_at_field, in_choices
from apps.common.ids import uuid7


class Channel(models.TextChoices):
    IN_APP = "IN_APP"
    SMS = "SMS"
    EMAIL = "EMAIL"


class Kind(models.TextChoices):
    STATUS = "STATUS"  # collapsible: only the latest status matters; expires after 72 h
    ACTION_REQUIRED = "ACTION_REQUIRED"  # the citizen must act; never expires, never collapsed
    SECURITY = "SECURITY"  # OTPs, password and phone changes; sent immediately


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


# Retries stop well inside this window. The outbox claim query only looks this far back, so
# PostgreSQL scans the latest monthly partitions instead of all of them.
CLAIM_WINDOW_DAYS = 14
MAX_ATTEMPTS = 8


class Notification(models.Model):
    """In-app inbox and the transactional outbox for SMS and email.

    Written in the same transaction as the change it announces, then delivered by a worker that
    leases the row. Partitioned by month; old months are dropped whole (cheap, no bloat).
    The database key is (id, created_at). See migration 0002.
    """

    public_id = models.UUIDField(default=uuid7, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,
        db_constraint=False,
    )
    request = models.ForeignKey(
        "service_requests.ServiceRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
        db_constraint=False,
    )
    channel = models.CharField(max_length=8, choices=Channel)
    kind = models.CharField(max_length=16, choices=Kind)
    template = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    collapse_key = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=10, choices=DeliveryStatus, default=DeliveryStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_default=Now())
    enqueued_at = models.DateTimeField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=32, null=True, blank=True)
    provider_message_id = models.CharField(max_length=128, null=True, blank=True)
    last_error = models.CharField(max_length=500, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "notification"
        constraints = [
            in_choices("channel", Channel, "notification"),
            in_choices("kind", Kind, "notification"),
            in_choices("status", DeliveryStatus, "notification"),
            models.CheckConstraint(
                condition=~Q(kind=Kind.ACTION_REQUIRED) | Q(expires_at__isnull=True),
                name="notification_action_required_never_expires",
            ),
            models.CheckConstraint(
                condition=~Q(status=DeliveryStatus.LEASED)
                | Q(lease_token__isnull=False, leased_until__isnull=False),
                name="notification_leased_has_lease",
            ),
            models.CheckConstraint(
                condition=Q(attempts__lte=MAX_ATTEMPTS), name="notification_attempts_max"
            ),
        ]
        indexes = [
            models.Index(
                fields=["next_attempt_at"],
                condition=Q(status=DeliveryStatus.PENDING),
                name="notification_pending_idx",
            ),  # outbox claim and sweeper
            models.Index(
                fields=["leased_until"],
                condition=Q(status=DeliveryStatus.LEASED),
                name="notification_leased_idx",
            ),  # expired-lease recovery
            models.Index(
                fields=["collapse_key", "-created_at"],
                condition=Q(status__in=[DeliveryStatus.PENDING, DeliveryStatus.LEASED]),
                name="notification_collapse_idx",
            ),  # supersede older STATUS messages
            models.Index(
                fields=["recipient", "-created_at"],
                condition=Q(channel=Channel.IN_APP),
                name="notification_inbox_idx",
            ),  # the citizen's inbox
            models.Index(fields=["public_id"], name="notification_public_id_idx"),
        ]
