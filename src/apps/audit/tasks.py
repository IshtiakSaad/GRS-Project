from celery import shared_task

from . import sealing


@shared_task(time_limit=120, soft_time_limit=100)
def seal_audit_log() -> dict:
    sealed = 0
    while (done := sealing.seal()) == sealing.BATCH:
        sealed += done
    sealed += done
    return {"sealed": sealed, "anchors_stored": sealing.store_anchors()}
