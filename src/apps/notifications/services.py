"""The outbox: a notification is a row written in the same transaction as the change it reports.

If the transaction rolls back, nothing is sent; if it commits, the row exists even when Redis is
down, and the sweeper (Phase 4) delivers it later. The broker only makes delivery fast.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Channel, Kind, Notification

logger = logging.getLogger(__name__)


def queue(
    recipient,
    template: str,
    payload: dict,
    *,
    channel: str = Channel.SMS,
    kind: str = Kind.SECURITY,
    request=None,
    expires_in: timedelta | None = None,
) -> Notification:
    expires_at = timezone.now() + expires_in if expires_in is not None else None
    notification = Notification.objects.create(
        recipient=recipient,
        request=request,
        channel=channel,
        kind=kind,
        template=template,
        payload=payload,
        expires_at=expires_at,
    )
    transaction.on_commit(lambda: _enqueue(notification))
    return notification


def _enqueue(notification: Notification) -> None:
    """Fast path only. A broker outage must not fail the user's request: the row is safe."""
    from .tasks import deliver

    try:
        deliver.delay(notification.pk, notification.created_at.isoformat())
    except Exception:  # noqa: BLE001 - any broker failure; the sweeper retries
        logger.warning("enqueue failed; notification %s left for the sweeper", notification.pk)
