"""Requests past their deadline: flag each once per SLA cycle and tell whoever must act.

The assigned officer is told, and so are the department's administrators, who can reassign
it. A request waiting on the citizen is not overdue: its clock is paused. Reopening starts a
new cycle, so a reopened request that runs late again is flagged again.
"""

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Now

from apps.accounts.models import Role, User
from apps.audit import services as audit
from apps.notifications import services as notifications
from apps.notifications.models import Kind

BATCH = 200


def escalate_overdue() -> int:
    from apps.service_requests.models import OPEN_STATUSES, ServiceRequest, Status

    rows = ServiceRequest.objects.filter(
        status__in=[s for s in OPEN_STATUSES if s != Status.AWAITING_CITIZEN],
        due_at__lt=Now(),
    ).filter(Q(escalated_at__isnull=True) | Q(escalated_at__lt=F("sla_started_at")))

    flagged = 0
    while True:
        with transaction.atomic():
            batch = list(
                rows.select_for_update(skip_locked=True, of=("self",))
                .select_related("assigned_officer")
                .order_by("due_at")[:BATCH]
            )
            admins = _admins({r.department_id for r in batch})
            for request in batch:
                ServiceRequest.objects.filter(pk=request.pk).update(escalated_at=Now())
                audit.record(
                    "request.overdue",
                    target=request,
                    request=request,
                    data={"due_at": request.due_at.isoformat()},
                )
                recipients = [request.assigned_officer] if request.assigned_officer else []
                recipients += admins.get(request.department_id, [])
                for user in recipients:
                    notifications.notify(
                        user,
                        "request_overdue",
                        {"tracking_no": request.tracking_no},
                        kind=Kind.ACTION_REQUIRED,
                        request=request,
                    )
            flagged += len(batch)
        if len(batch) < BATCH:
            return flagged


def _admins(department_ids: set[int]) -> dict[int, list[User]]:
    found: dict[int, list[User]] = {}
    for admin in User.objects.filter(
        role=Role.ADMIN, is_active=True, department_id__in=department_ids
    ):
        found.setdefault(admin.department_id, []).append(admin)
    return found
