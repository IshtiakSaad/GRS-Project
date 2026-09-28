from django.conf import settings
from django.db import models

from apps.common.db import created_at_field


class IdempotencyRecord(models.Model):
    """Makes a retried POST safe: same key and body return the stored response (Stripe semantics).

    A citizen on a 3G connection who taps "submit" twice, or whose app retries after a lost
    response, gets one request, not two. Purged after 24 hours.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    key = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)  # SHA-256 of method, path and body
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "idempotency_record"
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="idempotency_user_key_unique"),
        ]
        indexes = [models.Index(fields=["created_at"], name="idempotency_created_idx")]


class FeatureSwitch(models.Model):
    """Operational kill switches (e.g. pause SMS sending), changed without a deploy."""

    name = models.CharField(max_length=64, primary_key=True)
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=500, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feature_switch"
