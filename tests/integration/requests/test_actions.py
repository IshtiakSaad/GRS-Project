"""What each action does beyond changing the status."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Kind, Notification
from apps.service_requests.models import ServiceRequest, SlaPause, Status
from tests import factories

from ..auth.helpers import error_code
from .helpers import act, cast, in_state

pytestmark = pytest.mark.django_db


def _notice(request, template):
    return Notification.objects.filter(request=request, template=template).first()


def test_request_info_pauses_the_clock_and_asks_the_citizen(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    body = {"reason_code": "MISSING_DOCUMENT", "message": "Send the school certificate."}
    act(as_user(c.assigned), request, "request_info", body)

    request.refresh_from_db()
    assert request.info_request_count == 1
    assert SlaPause.objects.get(request=request, ended_at__isnull=True).reason_code == (
        "MISSING_DOCUMENT"
    )
    notice = _notice(request, "request_info_needed")
    assert notice.kind == Kind.ACTION_REQUIRED
    assert notice.expires_at is None  # the citizen must act; the message never expires


def test_the_reply_ends_the_pause_and_moves_the_deadline(as_user):
    c = cast()
    request = in_state(c, Status.AWAITING_CITIZEN)
    SlaPause.objects.filter(request=request).update(started_at=timezone.now() - timedelta(days=3))
    before = request.due_at

    act(as_user(c.owner), request, "respond", {"message": "Uploaded."})

    request.refresh_from_db()
    pause = SlaPause.objects.get(request=request)
    assert pause.ended_at is not None
    assert request.due_at > before


def test_a_third_information_request_needs_an_administrator(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    ServiceRequest.objects.filter(pk=request.pk).update(info_request_count=2)
    body = {"reason_code": "OTHER", "message": "Once more."}
    response = act(as_user(c.assigned), request, "request_info", body)
    assert response.status_code == 409
    assert error_code(response) == "INFO_REQUEST_LIMIT"


def test_resolve_opens_the_reopen_window(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    act(as_user(c.assigned), request, "resolve", {"note": "Certificate corrected."})
    request.refresh_from_db()
    assert request.resolution_note == "Certificate corrected."
    assert request.reopen_deadline - request.resolved_at == timedelta(days=30)
    assert _notice(request, "request_resolved").kind == Kind.STATUS


def test_reopen_starts_a_new_cycle_back_in_the_queue(as_user):
    c = cast()
    request = in_state(c, Status.RESOLVED)
    old_due = request.due_at
    act(as_user(c.owner), request, "reopen", {"reason": "Still misspelled."})
    request.refresh_from_db()
    assert request.status == Status.SUBMITTED
    assert request.assigned_officer is None
    assert request.resolution_note is None and request.reopen_deadline is None
    assert request.reopen_count == 1
    assert request.sla_started_at > request.submitted_at  # original submission time kept
    assert request.due_at != old_due


def test_reopen_limits(as_user):
    c = cast()
    late = in_state(c, Status.REJECTED)
    ServiceRequest.objects.filter(pk=late.pk).update(
        reopen_deadline=timezone.now() - timedelta(hours=1)
    )
    assert error_code(act(as_user(c.owner), late, "reopen", {"reason": "x"})) == (
        "REOPEN_WINDOW_CLOSED"
    )
    twice = in_state(c, Status.RESOLVED)
    ServiceRequest.objects.filter(pk=twice.pk).update(reopen_count=2)
    assert error_code(act(as_user(c.owner), twice, "reopen", {"reason": "x"})) == "REOPEN_LIMIT"


def test_a_rejection_near_the_deadline_is_flagged_for_review(as_user):
    c = cast()
    early = in_state(c, Status.IN_PROGRESS)
    late = in_state(c, Status.IN_PROGRESS)
    now = timezone.now()
    ServiceRequest.objects.filter(pk=late.pk).update(
        sla_started_at=now - timedelta(days=9), due_at=now + timedelta(days=1)
    )
    body = {"reason_code": "INCOMPLETE", "note": "No form."}
    for request in (early, late):
        act(as_user(c.assigned), request, "reject", body)
    flags = {
        a.request_id: a.data["late_rejection"]
        for a in AuditLog.objects.filter(action="request.reject")
    }
    assert flags == {early.pk: False, late.pk: True}


def test_withdrawing_tells_the_officer_and_closes_the_pause(as_user):
    c = cast()
    request = in_state(c, Status.AWAITING_CITIZEN)
    act(as_user(c.owner), request, "withdraw", {})
    request.refresh_from_db()
    assert request.closed_at is not None
    assert not SlaPause.objects.filter(request=request, ended_at__isnull=True).exists()
    assert _notice(request, "request_withdrawn").recipient_id == c.assigned.pk


def test_assign_only_to_an_active_officer_of_the_department(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.admin)
    wrong_dept = act(api, request, "assign", {"officer": str(c.outsider.public_id)})
    assert error_code(wrong_dept) == "INVALID_OFFICER"
    c.colleague.is_active = False
    c.colleague.save()
    inactive = act(api, request, "assign", {"officer": str(c.colleague.public_id)})
    assert error_code(inactive) == "INVALID_OFFICER"
    citizen = act(api, request, "assign", {"officer": str(c.owner.public_id)})
    assert error_code(citizen) == "INVALID_OFFICER"

    ok = act(api, request, "assign", {"officer": str(c.assigned.public_id)})
    assert ok.status_code == 200
    assert _notice(request, "request_assigned").recipient_id == c.assigned.pk


def test_reassign_counts_and_keeps_the_clock(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    api = as_user(c.admin)
    same = act(api, request, "reassign", {"officer": str(c.assigned.public_id), "reason": "x"})
    assert error_code(same) == "SAME_OFFICER"
    act(api, request, "reassign", {"officer": str(c.colleague.public_id), "reason": "Leave."})
    after = ServiceRequest.objects.get(pk=request.pk)
    assert after.assigned_officer_id == c.colleague.pk
    assert after.reassignment_count == 1
    assert after.due_at == request.due_at  # reassignment never resets the SLA


def test_start_tells_the_citizen(as_user):
    c = cast()
    request = in_state(c, Status.ASSIGNED)
    act(as_user(c.assigned), request, "start")
    assert _notice(request, "request_started").recipient_id == c.owner.pk


def test_unknown_action_is_404(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    assert act(as_user(c.admin), request, "set_priority").status_code == 404
    assert act(as_user(c.admin), request, "delete_everything").status_code == 404


def test_action_bodies_are_validated(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    response = act(as_user(c.assigned), request, "reject", {"reason_code": "BORED", "note": " "})
    assert response.status_code == 400
    assert set(response.json()["error"]["fields"]) == {"reason_code", "note"}


# --- priority ---------------------------------------------------------------------------------


def _set_priority(api, request, priority, etag):
    headers = {} if etag is None else {"HTTP_IF_MATCH": etag}
    return api.patch(
        f"/api/v1/requests/{request.public_id}/priority",
        {"priority": priority},
        format="json",
        **headers,
    )


def test_priority_needs_the_current_etag(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.colleague)
    assert _set_priority(api, request, "HIGH", None).status_code == 428
    assert _set_priority(api, request, "HIGH", '"7"').status_code == 412
    ok = _set_priority(api, request, "HIGH", '"1"')
    assert ok.status_code == 200
    assert ok.json()["priority"] == "HIGH"
    assert ok["ETag"] == '"2"'
    assert _set_priority(api, request, "URGENT", '"1"').status_code == 412  # stale copy


@pytest.mark.parametrize(
    ("who", "code"),
    [("owner", 403), ("stranger", 404), ("colleague", 200), ("outsider", 404), ("admin", 200)],
)
def test_who_may_set_priority(as_user, who, code):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    assert _set_priority(as_user(c.by_name(who)), request, "LOW", '"1"').status_code == code


def test_priority_of_a_closed_request_cannot_change(as_user):
    c = cast()
    request = in_state(c, Status.RESOLVED)
    assert _set_priority(as_user(c.admin), request, "LOW", '"1"').status_code == 409


def test_admins_act_only_with_a_two_step_session(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.admin, mfa=False)
    response = act(api, request, "assign", {"officer": str(c.assigned.public_id)})
    assert response.status_code == 403
    assert api.get(f"/api/v1/requests/{request.public_id}").status_code == 403


def test_a_deactivated_officer_loses_access_at_once(as_user):
    c = cast()
    request = in_state(c, Status.ASSIGNED)
    api = as_user(c.assigned)
    c.assigned.is_active = False
    c.assigned.token_version += 1
    c.assigned.save()
    assert act(api, request, "start").status_code == 401


def test_officer_actions_on_an_unassigned_request_of_another_officer(as_user):
    c = cast()
    other = factories.officer(c.category.department)
    request = in_state(c, Status.ASSIGNED)
    response = act(as_user(other), request, "start")
    assert response.status_code == 403  # a colleague sees it but cannot act on it
