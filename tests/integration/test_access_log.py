"""Staff access is recorded: every open, change, download, and every list page."""

import pytest
from django.utils import timezone

from apps.audit.models import AccessEvent, AccessEventItem, AccessKind
from apps.collab.models import Attachment, AttachmentStatus
from apps.service_requests.models import ServiceRequest, Status
from apps.service_requests.tracking import format_tracking_no

from .auth.helpers import error_code
from .requests.helpers import act, cast, in_state

pytestmark = pytest.mark.django_db


def _numbered(request):
    """A real tracking number (the factory's has no valid check digit)."""
    number = format_tracking_no(2026, 900000 + request.pk)
    ServiceRequest.objects.filter(pk=request.pk).update(tracking_no=number)
    request.tracking_no = number
    return request


def _events(request, kind=None):
    rows = AccessEvent.objects.filter(request_id=request.pk)
    return rows.filter(kind=kind) if kind else rows


def test_a_staff_view_is_recorded_with_the_office(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    as_user(c.colleague).get(f"/api/v1/requests/{request.public_id}")
    event = _events(request).get()
    assert (event.kind, event.actor_id, event.actor_role) == (
        AccessKind.VIEW,
        c.colleague.pk,
        "OFFICER",
    )
    assert event.actor_department_id == c.category.department_id


def test_citizens_reading_their_own_are_not_logged(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    api.get(f"/api/v1/requests/{request.public_id}")
    api.get("/api/v1/requests")
    assert not AccessEvent.objects.exists()


def test_every_staff_read_of_a_request_is_recorded(as_user):
    c = cast()
    request = _numbered(in_state(c, Status.IN_PROGRESS))
    api = as_user(c.assigned)
    for path in ("", "/timeline", "/comments", "/attachments"):
        assert api.get(f"/api/v1/requests/{request.public_id}{path}").status_code == 200
    api.get(f"/api/v1/requests/by-tracking/{request.tracking_no}")
    assert _events(request, AccessKind.VIEW).count() == 5


def test_changes_are_recorded(as_user):
    c = cast()
    request = in_state(c, Status.ASSIGNED)
    api = as_user(c.assigned)
    act(api, request, "start")
    api.post(f"/api/v1/requests/{request.public_id}/comments", {"body": "Checking."}, format="json")
    assert _events(request, AccessKind.UPDATE).count() == 2


def test_a_claim_is_recorded(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    as_user(c.colleague).post("/api/v1/queue/claim-next")
    assert _events(request, AccessKind.UPDATE).count() == 1


def test_a_staff_download_is_recorded(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    attachment = Attachment.objects.create(
        request=request,
        uploaded_by=c.owner,
        original_name="form.pdf",
        declared_content_type="application/pdf",
        declared_size=10,
        detected_content_type="application/pdf",
        size_bytes=10,
        sha256="0" * 64,
        storage_key=f"requests/{request.public_id}/x",
        status=AttachmentStatus.READY,
        verified_at=timezone.now(),
    )
    as_user(c.colleague).get(f"/api/v1/attachments/{attachment.public_id}/download")
    assert _events(request, AccessKind.DOWNLOAD).count() == 1


def test_a_list_page_records_every_request_it_showed(as_user):
    c = cast()
    shown = [in_state(c, Status.SUBMITTED) for _ in range(3)]
    in_state(cast(), Status.SUBMITTED)  # another department's: not shown, not recorded
    as_user(c.colleague).get("/api/v1/requests")
    event = AccessEvent.objects.get(kind=AccessKind.LIST)
    assert event.item_count == 3
    items = AccessEventItem.objects.filter(event_id=event.pk)
    assert {i.request_id for i in items} == {r.pk for r in shown}
    assert {i.created_at for i in items} == {event.created_at}  # same partition as the event


def test_the_queue_page_is_a_list_too(as_user):
    c = cast()
    in_state(c, Status.SUBMITTED)
    as_user(c.colleague).get("/api/v1/queue")
    assert AccessEvent.objects.get(kind=AccessKind.LIST).item_count == 1


# --- the citizen's access log -----------------------------------------------------------------


def _log(api, request):
    return api.get(f"/api/v1/requests/{request.public_id}/access-log")


def test_the_citizen_sees_which_office_looked_never_who(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    as_user(c.assigned).get(f"/api/v1/requests/{request.public_id}")
    as_user(c.colleague).get("/api/v1/requests")
    body = _log(as_user(c.owner), request).json()
    [entry] = body["results"]
    assert entry["kind"] == "VIEW" and entry["role"] == "OFFICER"
    assert entry["office"]["code"] == c.category.department.code
    assert "actor" not in entry and c.assigned.full_name not in str(body)
    assert body["list_appearances"] == 1


def test_auditors_see_who(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    as_user(c.assigned).get(f"/api/v1/requests/{request.public_id}")
    body = _log(as_user(c.admin), request).json()
    assert body["results"][-1]["actor"]["name"] == c.assigned.full_name
    assert _events(request).filter(actor_id=c.admin.pk).exists()  # the auditor's look, too


@pytest.mark.parametrize(("who", "code"), [("assigned", 403), ("stranger", 404)])
def test_the_log_is_the_citizens_and_the_auditors(as_user, who, code):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    assert _log(as_user(c.by_name(who)), request).status_code == code


# --- break-glass ------------------------------------------------------------------------------


def _break_glass(api, request, reason="CITIZEN_COMPLAINT", note=None):
    body = {"tracking_no": _numbered(request).tracking_no, "reason": reason}
    if note is not None:
        body["note"] = note
    return api.post("/api/v1/requests/break-glass", body, format="json")


def test_an_officer_opens_a_request_outside_their_scope_with_a_reason(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    api = as_user(c.outsider)
    assert api.get(f"/api/v1/requests/{request.public_id}").status_code == 404  # normally
    opened = _break_glass(api, request)
    assert opened.status_code == 200
    assert opened.json()["id"] == str(request.public_id)
    event = _events(request).get(actor_id=c.outsider.pk)
    assert event.break_glass_reason == "CITIZEN_COMPLAINT"
    # Read-only: acting still needs the request to be in scope.
    assert act(api, request, "resolve", {"note": "x"}).status_code == 404


def test_other_needs_an_explanation(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.outsider)
    assert "note" in _break_glass(api, request, "OTHER", "short").json()["error"]["fields"]
    explained = "Citizen visited the Dhaka office in person."
    assert _break_glass(api, request, "OTHER", explained).status_code == 200
    assert _events(request).get().break_glass_note == explained


def test_break_glass_checks_the_number_and_the_reason(as_user):
    c = cast()
    api = as_user(c.outsider)
    valid = format_tracking_no(2026, 1)
    wrong_check_digit = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    bad = api.post(
        "/api/v1/requests/break-glass",
        {"tracking_no": wrong_check_digit, "reason": "AUDIT"},
        format="json",
    )
    assert error_code(bad) == "INVALID_TRACKING_NO"
    request = in_state(c, Status.SUBMITTED)
    assert _break_glass(api, request, "CURIOSITY").status_code == 400
    assert not AccessEvent.objects.exists()


def test_only_officers_break_glass(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    assert _break_glass(as_user(c.owner), request).status_code == 403
    assert _break_glass(as_user(c.admin), request).status_code == 403  # admins see all anyway


def test_the_break_glass_report(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    _break_glass(as_user(c.outsider), request, "AUDIT")
    as_user(c.colleague).get(f"/api/v1/requests/{request.public_id}")  # in scope: not listed
    admin = as_user(c.admin)
    [row] = admin.get("/api/v1/admin/break-glass").json()["results"]
    assert (row["break_glass_reason"], row["actor"]["name"]) == ("AUDIT", c.outsider.full_name)
    assert row["request"]["tracking_no"] == request.tracking_no
    assert admin.get("/api/v1/admin/break-glass?days=0").status_code == 400
