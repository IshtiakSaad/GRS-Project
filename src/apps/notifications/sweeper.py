"""The outbox's safety net, run by beat every 30 seconds.

The broker is only the fast path. A row can be left behind when Redis was down at commit, when
a worker crashed while holding a lease, or when a failed send was put back for a later retry.
The sweeper finds each of these and hands it to a worker again; delivery's lease makes a
duplicate hand-off harmless.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Now

from .delivery import _in
from .models import CLAIM_WINDOW_DAYS, MAX_ATTEMPTS, DeliveryStatus, Notification

logger = logging.getLogger(__name__)

# A fresh row is enqueued on commit; give that fast path time before stepping in.
GRACE = timedelta(seconds=60)
# A row enqueued but not yet claimed may be sitting in a long queue; ask again after this.
REENQUEUE_AFTER = timedelta(minutes=5)
BATCH = 500


def _recent():
    """Only the latest partitions: retries stop well inside the claim window."""
    return Notification.objects.filter(created_at__gte=_in(-timedelta(days=CLAIM_WINDOW_DAYS)))


def expire() -> int:
    """Status messages nobody delivered in time are pointless now; stop trying."""
    return (
        _recent()
        .filter(status=DeliveryStatus.PENDING, expires_at__lte=Now())
        .update(status=DeliveryStatus.EXPIRED, lease_token=None, leased_until=None)
    )


def recover_leases() -> int:
    """A worker died holding the row. The crash counts as an attempt, so a message that kills
    workers every time still stops at the attempt cap."""
    stale = _recent().filter(status=DeliveryStatus.LEASED, leased_until__lt=Now())
    failed = stale.filter(attempts__gte=MAX_ATTEMPTS - 1).update(
        status=DeliveryStatus.FAILED,
        lease_token=None,
        leased_until=None,
        last_error="worker lost the lease",
    )
    retried = stale.update(
        status=DeliveryStatus.PENDING,
        attempts=F("attempts") + 1,
        lease_token=None,
        leased_until=None,
        enqueued_at=None,
        next_attempt_at=Now(),
        last_error="worker lost the lease",
    )
    return failed + retried


def due() -> list[tuple[int, str]]:
    """Mark due rows as enqueued and return them. SKIP LOCKED lets two sweepers run safely."""
    with transaction.atomic():
        rows = list(
            _recent()
            .filter(status=DeliveryStatus.PENDING, next_attempt_at__lte=_in(-GRACE))
            .filter(Q(enqueued_at__isnull=True) | Q(enqueued_at__lte=_in(-REENQUEUE_AFTER)))
            .order_by("next_attempt_at")
            .select_for_update(skip_locked=True)
            .values_list("pk", "created_at")[:BATCH]
        )
        if rows:
            Notification.objects.filter(pk__in=[pk for pk, _ in rows]).update(enqueued_at=Now())
    return [(pk, created.isoformat()) for pk, created in rows]


def sweep() -> dict[str, int]:
    from .tasks import deliver

    expired = expire()
    recovered = recover_leases()
    sent = 0
    for pk, created_at in due():
        try:
            deliver.delay(pk, created_at)
        except Exception:  # noqa: BLE001 - broker still down; enqueued_at ages, we retry later
            logger.warning("sweeper could not enqueue; will retry")
            break
        sent += 1
    return {"expired": expired, "recovered": recovered, "enqueued": sent}
