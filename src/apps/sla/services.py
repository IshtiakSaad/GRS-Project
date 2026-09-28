"""Deadlines from the database: which days are closed, and a request's current due date.

`due_at` on a request is a cached value of this function; anything that changes an input
(a pause ends, the request is reopened, later: a holiday is added) recomputes it.
"""

from datetime import date, datetime, timedelta

from django.db.models import Q

from apps.directory.models import Holiday, SlaSuspension

from .calendar import MAX_SPAN_DAYS, Calendar, due_at, local_date


def calendar_for(department_id: int, start: date) -> Calendar:
    end = start + timedelta(days=MAX_SPAN_DAYS)
    closed = set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    suspensions = SlaSuspension.objects.filter(
        Q(scope_department__isnull=True) | Q(scope_department_id=department_id),
        starts_on__lte=end,
        ends_on__gte=start,
    ).values_list("starts_on", "ends_on")
    for first, last in suspensions:
        day = max(first, start)
        while day <= min(last, end):
            closed.add(day)
            day += timedelta(days=1)
    return Calendar(closed)


def compute_due_at(request) -> datetime:
    """Deadline of the current cycle: from `sla_started_at`, extended by the finished pauses
    that began in this cycle. An open pause is not counted until it ends."""
    started = request.sla_started_at
    pauses = request.pauses.filter(started_at__gte=started, ended_at__isnull=False).values_list(
        "started_at", "ended_at"
    )
    calendar = calendar_for(request.department_id, local_date(started))
    return due_at(calendar, started, request.category.target_working_days, pauses)
