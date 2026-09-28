from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.service_requests.models import ServiceRequest, Status
from apps.sla.overdue import escalate_overdue
from tests import factories

from .helpers import cast, in_state

pytestmark = pytest.mark.django_db


def _late(c, status=Status.IN_PROGRESS):
    request = in_state(c, status)
    ServiceRequest.objects.filter(pk=request.pk).update(due_at=timezone.now() - timedelta(hours=1))
    return request


def _told(template="request_overdue"):
    return set(Notification.objects.filter(template=template).values_list("recipient", flat=True))


def test_an_overdue_request_is_flagged_and_staff_are_told():
    c = cast()
    admin = factories.admin(department=c.category.department)
    request = _late(c)
    assert escalate_overdue() == 1
    request.refresh_from_db()
    assert request.escalated_at is not None
    assert _told() == {c.assigned.pk, admin.pk}  # not c.admin: another department's business
    assert AuditLog.objects.filter(action="request.overdue", target_id=request.pk).exists()


def test_it_is_flagged_once_per_cycle():
    c = cast()
    _late(c)
    escalate_overdue()
    assert escalate_overdue() == 0
    assert Notification.objects.filter(template="request_overdue").count() == 1


def test_a_reopened_request_that_runs_late_again_is_flagged_again():
    c = cast()
    request = _late(c)
    escalate_overdue()
    ServiceRequest.objects.filter(pk=request.pk).update(  # flagged, then reopened
        escalated_at=timezone.now() - timedelta(days=1),
        sla_started_at=timezone.now() - timedelta(hours=12),
    )
    assert escalate_overdue() == 1


def test_an_unassigned_request_goes_to_the_department_admins():
    c = cast()
    admin = factories.admin(department=c.category.department)
    _late(c, Status.SUBMITTED)
    escalate_overdue()
    assert _told() == {admin.pk}


@pytest.mark.parametrize("status", [Status.AWAITING_CITIZEN, Status.RESOLVED])
def test_paused_and_finished_requests_are_not_overdue(status):
    c = cast()
    _late(c, status)
    assert escalate_overdue() == 0


def test_a_request_within_its_deadline_is_left_alone():
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    ServiceRequest.objects.filter(pk=request.pk).update(due_at=timezone.now() + timedelta(days=1))
    assert escalate_overdue() == 0
