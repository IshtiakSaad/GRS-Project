import pytest

from apps.audit.models import AuditLog
from apps.collab.models import Comment
from apps.notifications.models import Notification
from apps.service_requests.models import SlaPause, Status

from ..auth.helpers import error_code
from ..requests.helpers import cast, in_state

pytestmark = pytest.mark.django_db


def _post(api, request, body="The form is attached.", **extra):
    return api.post(
        f"/api/v1/requests/{request.public_id}/comments", {"body": body, **extra}, format="json"
    )


def _list(api, request):
    return api.get(f"/api/v1/requests/{request.public_id}/comments")


def test_a_citizen_comments_on_their_request(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    response = _post(as_user(c.owner), request)
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "The form is attached." and body["internal"] is False
    assert body["author"]["name"] == c.owner.full_name  # your own name is yours to see
    comment = Comment.objects.get(public_id=body["id"])
    assert AuditLog.objects.filter(action="comment.create", target_id=comment.pk).exists()


def test_citizens_cannot_write_internal_comments(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    response = _post(as_user(c.owner), request, internal=True)
    assert response.status_code == 403
    assert error_code(response) == "NOT_ALLOWED"


def test_internal_comments_never_reach_the_citizen(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    _post(as_user(c.assigned), request, "Check the land record first.", internal=True)
    _post(as_user(c.assigned), request, "We are checking the record.")

    citizen = _list(as_user(c.owner), request).json()["results"]
    assert [row["body"] for row in citizen] == ["We are checking the record."]
    author = citizen[0]["author"]
    assert author == {"role": "OFFICER", "department": c.category.department.code}  # no name

    staff = _list(as_user(c.colleague), request).json()["results"]
    assert [row["internal"] for row in staff] == [True, False]  # oldest first
    assert staff[0]["author"]["name"] == c.assigned.full_name


def test_a_public_staff_comment_tells_the_citizen(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    _post(as_user(c.assigned), request, "Internal note.", internal=True)
    assert not Notification.objects.filter(template="request_comment").exists()
    _post(as_user(c.assigned), request, "Please bring the original.")
    sms = Notification.objects.get(template="request_comment")
    assert sms.recipient_id == c.owner.pk
    assert sms.payload == {"tracking_no": request.tracking_no}  # never the comment text (D1)


def test_the_citizens_comment_is_their_answer(as_user):
    c = cast()
    request = in_state(c, Status.AWAITING_CITIZEN)
    assert _post(as_user(c.owner), request, "Here is the certificate.").status_code == 201
    request.refresh_from_db()
    assert request.status == Status.IN_PROGRESS
    assert not SlaPause.objects.filter(request=request, ended_at__isnull=True).exists()
    event = request.events.latest("id")
    assert (event.event_type, event.data) == ("respond", {"message": "Here is the certificate."})


def test_a_citizen_can_comment_without_resuming(as_user):
    c = cast()
    request = in_state(c, Status.AWAITING_CITIZEN)
    _post(as_user(c.owner), request, "I will send it tomorrow.", respond=False)
    request.refresh_from_db()
    assert request.status == Status.AWAITING_CITIZEN


def test_drafts_have_no_conversation(as_user):
    c = cast()
    draft = in_state(c, Status.DRAFT)
    assert error_code(_post(as_user(c.owner), draft)) == "NOT_SUBMITTED"


@pytest.mark.parametrize("who", ["stranger", "outsider"])
def test_comments_are_scoped(as_user, who):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.by_name(who))
    assert _post(api, request).status_code == 404
    assert _list(api, request).status_code == 404


def test_an_empty_comment_is_refused(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    response = _post(as_user(c.owner), request, " ​ ")
    assert response.status_code == 400
    assert "body" in response.json()["error"]["fields"]


def test_anonymous_callers_cannot_read_comments(api):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    assert _list(api, request).status_code == 401
