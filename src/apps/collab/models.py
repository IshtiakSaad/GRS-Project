from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThan

from apps.common.db import created_at_field, in_choices
from apps.common.ids import uuid7

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Comment(models.Model):
    public_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    request = models.ForeignKey(
        "service_requests.ServiceRequest",
        on_delete=models.PROTECT,
        related_name="comments",
        db_index=False,  # covered by comment_request_idx
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    body = models.CharField(max_length=5000)  # varchar: PostgreSQL enforces the limit
    is_internal = models.BooleanField(default=False)  # staff only; never shown to citizens
    created_at = created_at_field()

    class Meta:
        db_table = "comment"
        constraints = [
            models.CheckConstraint(
                condition=GreaterThan(Length("body"), 0), name="comment_body_not_empty"
            ),
        ]
        indexes = [models.Index(fields=["request", "created_at"], name="comment_request_idx")]


class AttachmentStatus(models.TextChoices):
    PENDING = "PENDING"  # upload URL issued, file not confirmed
    VERIFYING = "VERIFYING"  # confirmed, checks running
    READY = "READY"  # passed size, type, hash and scan checks; downloadable
    REJECTED = "REJECTED"  # failed a check; never downloadable


class Attachment(models.Model):
    public_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    request = models.ForeignKey(
        "service_requests.ServiceRequest",
        on_delete=models.PROTECT,
        related_name="attachments",
        db_index=False,  # covered by attachment_request_idx
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    original_name = models.CharField(max_length=255)
    declared_content_type = models.CharField(max_length=100)
    declared_size = models.PositiveIntegerField()
    detected_content_type = models.CharField(max_length=100, null=True, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, null=True, blank=True)
    storage_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=10, choices=AttachmentStatus, default=AttachmentStatus.PENDING
    )
    rejection_reason = models.CharField(max_length=64, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "attachment"
        constraints = [
            in_choices("status", AttachmentStatus, "attachment"),
            models.CheckConstraint(
                condition=Q(declared_size__gt=0, declared_size__lte=MAX_ATTACHMENT_BYTES),
                name="attachment_declared_size_range",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__isnull=True)
                | Q(size_bytes__gt=0, size_bytes__lte=MAX_ATTACHMENT_BYTES),
                name="attachment_size_range",
            ),
            # Only a fully verified file can be READY.
            models.CheckConstraint(
                condition=~Q(status=AttachmentStatus.READY)
                | Q(
                    sha256__isnull=False,
                    size_bytes__isnull=False,
                    detected_content_type__isnull=False,
                    verified_at__isnull=False,
                ),
                name="attachment_ready_is_verified",
            ),
            models.CheckConstraint(
                condition=~Q(status=AttachmentStatus.REJECTED) | Q(rejection_reason__isnull=False),
                name="attachment_rejected_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(sha256__isnull=True) | Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="attachment_sha256_format",
            ),
        ]
        indexes = [
            models.Index(fields=["request", "created_at"], name="attachment_request_idx"),
            models.Index(
                fields=["created_at"],
                condition=Q(status__in=[AttachmentStatus.PENDING, AttachmentStatus.VERIFYING]),
                name="attachment_unfinished_idx",
            ),  # verifier sweep and stale-upload cleanup
        ]
