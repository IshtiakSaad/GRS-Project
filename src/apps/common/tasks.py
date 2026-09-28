from celery import shared_task

from . import idempotency


@shared_task(time_limit=120, soft_time_limit=100)
def purge_idempotency_records() -> int:
    return idempotency.purge_expired()
