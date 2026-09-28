"""Deliver one outbox row: lease it, send it outside any transaction, record the result.

The lease makes delivery safe to run twice: only the worker holding the lease token can
complete the row, and a crashed worker's lease simply expires; the sweeper (sweeper.py) then
hands the row to a worker again.
"""

import logging
import random
import uuid
from datetime import timedelta

from django.db.models import DateTimeField, ExpressionWrapper
from django.db.models.functions import Now
from django.utils import timezone

from . import providers
from .models import MAX_ATTEMPTS, Channel, DeliveryStatus, Notification
from .templates import SENSITIVE, render

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
BACKOFF_CAP = timedelta(minutes=30)


def _in(delta: timedelta) -> ExpressionWrapper:
    return ExpressionWrapper(Now() + delta, output_field=DateTimeField())


def backoff(attempts: int) -> timedelta:
    """Exponential backoff with full jitter: retries from many rows do not arrive together."""
    ceiling = min(BACKOFF_CAP.total_seconds(), 30 * 2**attempts)
    return timedelta(seconds=random.uniform(0, ceiling))  # noqa: S311 - jitter, not security


def deliver(notification_id: int, created_at) -> str:
    """Returns the resulting status, or "skipped" if another worker holds or finished the row."""
    token = uuid.uuid4()
    rows = Notification.objects.filter(pk=notification_id, created_at=created_at)
    claimed = rows.filter(status=DeliveryStatus.PENDING, next_attempt_at__lte=Now()).update(
        status=DeliveryStatus.LEASED, leased_until=_in(LEASE), lease_token=token
    )
    if not claimed:
        return "skipped"
    n = rows.select_related("recipient").get()
    mine = rows.filter(lease_token=token)

    if n.expires_at is not None and n.expires_at <= timezone.now():
        mine.update(**_finished(n, DeliveryStatus.EXPIRED))
        return DeliveryStatus.EXPIRED

    try:
        provider_id = _send(n)
    except Exception as exc:  # noqa: BLE001 - any provider failure is retried
        attempts = n.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            mine.update(**_finished(n, DeliveryStatus.FAILED), attempts=attempts)
            logger.error("notification %s failed permanently: %s", n.pk, exc)
            return DeliveryStatus.FAILED
        mine.update(
            status=DeliveryStatus.PENDING,
            attempts=attempts,
            next_attempt_at=_in(backoff(attempts)),
            leased_until=None,
            lease_token=None,
            enqueued_at=None,
            last_error=str(exc)[:500],
        )
        logger.warning("notification %s attempt %s failed: %s", n.pk, attempts, exc)
        return DeliveryStatus.PENDING

    mine.update(**_finished(n, DeliveryStatus.SENT), sent_at=Now(), provider_message_id=provider_id)
    return DeliveryStatus.SENT


def _send(n: Notification) -> str:
    subject, body = render(n.template, n.recipient.preferred_language, n.payload)
    if n.channel == Channel.SMS:
        return providers.send_sms(n.recipient.phone, body)
    if n.channel == Channel.EMAIL:
        if not n.recipient.email:
            raise providers.ProviderError("recipient has no email address")
        return providers.send_email(n.recipient.email, subject, body)
    raise providers.ProviderError(f"channel {n.channel} is not delivered by a provider")


def _finished(n: Notification, status: str) -> dict:
    fields = {"status": status, "leased_until": None, "lease_token": None}
    if n.template in SENSITIVE:
        fields["payload"] = {"erased": True}  # the code is no longer needed anywhere
    return fields
