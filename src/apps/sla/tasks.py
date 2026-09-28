from celery import shared_task

from . import services


@shared_task(time_limit=600, soft_time_limit=540, acks_late=True)
def recompute_due_dates(department_id: int | None = None, category_id: int | None = None) -> int:
    return services.recompute_open(department_id=department_id, category_id=category_id)


@shared_task(time_limit=300, soft_time_limit=270)
def escalate_overdue() -> int:
    from . import overdue

    return overdue.escalate_overdue()
