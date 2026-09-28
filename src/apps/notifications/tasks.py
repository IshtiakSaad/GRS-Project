from celery import shared_task

from . import delivery


@shared_task(time_limit=45, soft_time_limit=30)
def deliver(notification_id: int, created_at: str) -> str:
    return delivery.deliver(notification_id, created_at)
