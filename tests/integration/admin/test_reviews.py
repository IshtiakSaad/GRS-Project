from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.service_requests.models import Review, ServiceRequest, Status
from tests import factories

from ..auth.helpers import error_code
from ..requests.helpers import act, cast, in_state

pytestmark = pytest.mark.django_db

REJECT = {"reason_code": "INCOMPLETE", "note": "Form missing."}


def _late_rejection(as_user, c):
    request = in_state(c, Status.IN_PROGRESS)
    now = timezone.now()
    ServiceRequest.objects.filter(pk=request.pk).update(
        sla_started_at=now - timedelta(days=9), due_at=now + timedelta(days=1)
    )
    assert act(as_user(c.assigned), request, "reject", REJECT).status_code == 200
    return request, Review.objects.get(request=request)


def _decide(api, review, decision, note=None):
    body = {"decision": decision} | ({"note": note} if note is not None else {})
    return api.post(f"/api/v1/admin/reviews/{review.public_id}/decision", body, format="json")


def test_a_late_rejection_is_queued_for_review(as_user):
    c = cast()
    request, review = _late_rejection(as_user, c)
    assert (review.reason, review.decided_status, review.officer_id) == (
        "LATE_REJECTION",
        Status.REJECTED,
        c.assigned.pk,
    )
    rows = as_user(c.admin).get("/api/v1/admin/reviews?status=PENDING").json()["results"]
    assert [r["request"]["tracking_no"] for r in rows] == [request.tracking_no]
    assert rows[0]["request"]["rejection_note"] == "Form missing."


def test_an_early_rejection_is_not(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    ServiceRequest.objects.filter(pk=request.pk).update(due_at=timezone.now() + timedelta(days=20))
    act(as_user(c.assigned), request, "reject", REJECT)
    assert not Review.objects.exists()


@pytest.mark.parametrize(("rate", "queued"), [(1.0, True), (0.0, False)])
def test_resolutions_are_sampled(as_user, settings, rate, queued):
    settings.REVIEW_SAMPLE_RATE = rate
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    act(as_user(c.assigned), request, "resolve", {"note": "Corrected."})
    assert Review.objects.filter(request=request, reason="SAMPLE").exists() is queued


def test_upholding_closes_the_review(as_user):
    c = cast()
    request, review = _late_rejection(as_user, c)
    response = _decide(as_user(c.admin), review, "UPHOLD")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UPHELD" and body["reviewer"]["id"] == str(c.admin.public_id)
    request.refresh_from_db()
    assert request.status == Status.REJECTED
    assert AuditLog.objects.filter(action="review.decide", target_id=review.pk).exists()


def test_overturning_sends_the_request_back_with_a_new_deadline(as_user):
    c = cast()
    request, review = _late_rejection(as_user, c)
    response = _decide(as_user(c.admin), review, "OVERTURN", "The form was attached on day 2.")
    assert response.json()["status"] == "OVERTURNED"
    request.refresh_from_db()
    assert request.status == Status.SUBMITTED
    assert request.assigned_officer is None and request.rejection_reason_code is None
    assert request.due_at > timezone.now() + timedelta(days=1)
    assert request.reopen_count == 0  # not the citizen's reopen; their allowance is untouched
    event = request.events.latest("id")
    assert (event.event_type, event.actor_id) == ("overturn", c.admin.pk)
    assert Notification.objects.filter(template="request_reopened", recipient=c.owner).exists()


def test_overturning_needs_a_reason(as_user):
    c = cast()
    _, review = _late_rejection(as_user, c)
    response = _decide(as_user(c.admin), review, "OVERTURN", "wrong")
    assert response.status_code == 400
    assert "note" in response.json()["error"]["fields"]


def test_a_review_is_decided_once(as_user):
    c = cast()
    _, review = _late_rejection(as_user, c)
    _decide(as_user(c.admin), review, "UPHOLD")
    assert error_code(_decide(as_user(c.admin), review, "UPHOLD")) == "ALREADY_REVIEWED"


def test_nobody_reviews_their_own_decision(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    now = timezone.now()
    ServiceRequest.objects.filter(pk=request.pk).update(
        sla_started_at=now - timedelta(days=9), due_at=now + timedelta(days=1)
    )
    act(as_user(c.admin), request, "reject", REJECT)  # an administrator rejected it late
    review = Review.objects.get()
    response = _decide(as_user(c.admin), review, "UPHOLD")
    assert (response.status_code, error_code(response)) == (403, "OWN_DECISION")
    other = factories.admin()
    assert _decide(as_user(other), review, "UPHOLD").status_code == 200


def test_a_request_the_citizen_already_reopened_cannot_be_overturned(as_user):
    c = cast()
    request, review = _late_rejection(as_user, c)
    act(as_user(c.owner), request, "reopen", {"reason": "Still wrong."})
    response = _decide(as_user(c.admin), review, "OVERTURN", "The form was attached on day 2.")
    assert error_code(response) == "REQUEST_CHANGED"
    assert _decide(as_user(c.admin), review, "UPHOLD").status_code == 200


def test_the_queue_filters(as_user, settings):
    settings.REVIEW_SAMPLE_RATE = 1.0
    c = cast()
    _late_rejection(as_user, c)
    resolved = in_state(c, Status.IN_PROGRESS)
    act(as_user(c.assigned), resolved, "resolve", {"note": "Done."})
    api = as_user(c.admin)
    by_reason = api.get("/api/v1/admin/reviews?reason=SAMPLE").json()["results"]
    assert [r["reason"] for r in by_reason] == ["SAMPLE"]
    dept = c.category.department.code
    assert len(api.get(f"/api/v1/admin/reviews?department={dept}").json()["results"]) == 2
    assert api.get("/api/v1/admin/reviews?department=NOPE").json()["results"] == []


def test_unknown_review(as_user):
    import uuid

    c = cast()
    response = as_user(c.admin).post(
        f"/api/v1/admin/reviews/{uuid.uuid4()}/decision", {"decision": "UPHOLD"}, format="json"
    )
    assert response.status_code == 404


@pytest.mark.parametrize("who", ["owner", "assigned"])
def test_only_administrators_see_the_queue(as_user, who):
    c = cast()
    assert as_user(c.by_name(who)).get("/api/v1/admin/reviews").status_code == 403
