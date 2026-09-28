from botocore.exceptions import BotoCoreError, ClientError
from celery import shared_task

from . import verification


@shared_task(
    autoretry_for=(BotoCoreError, ClientError),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=8,
    time_limit=120,
    soft_time_limit=100,
)
def verify_attachment(attachment_id: int) -> str:
    return verification.verify(attachment_id)


@shared_task(time_limit=60, soft_time_limit=50)
def sweep_stuck_attachments() -> int:
    ids = verification.stuck()
    for pk in ids:
        verify_attachment.delay(pk)
    return len(ids)
