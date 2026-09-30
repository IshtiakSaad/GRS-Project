import itertools
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Holiday, SlaSuspension
from apps.notifications.models import Kind, Notification
from apps.service_requests.models import ServiceRequest, Status
from apps.service_requests.tracking import damm, parse_tracking_no
from apps.sla.calendar import DHAKA
from tests import factories

from ..auth.helpers import error_code
from .helpers import act, cast, draft_body, in_state, key

pytestmark = pytest.mark.django_db


_titles = itertools.count(1)


def _submitted(c, api, **headers):
    """A submitted request with a title of its own, so it is never a duplicate prompt."""
    request = factories.draft(owner=c.owner, cat=c.category, title=f"Request {next(_titles)}")
    response = act(api, request, "submit", **headers)
    assert response.status_code == 200, response.content
    request.refresh_from_db()
    return request, response


def test_submit_numbers_times_and_announces_the_request(as_user):
    c = cast()
    request, response = _submitted(c, as_user(c.owner))
    body = response.json()

    number = body["tracking_no"]
    assert parse_tracking_no(number) == number
    assert damm(number.replace("-", "")) == 0
    assert number[:2] == f"{timezone.now().astimezone(DHAKA).year % 100:02d}"
    assert request.submitted_at == request.sla_started_at
    assert request.due_at.astimezone(DHAKA).hour == 23
    assert request.content_hash and len(request.content_hash) == 64

    audit = AuditLog.objects.get(request=request, action="request.submit")
    assert audit.data["tracking_no"] == number  # every issued number is on record (gaps)
    sms = Notification.objects.get(request=request)
    assert (sms.template, sms.kind, sms.recipient_id) == (
        "request_submitted",
        Kind.STATUS,
        c.owner.pk,
    )
    assert sms.payload == {"tracking_no": number}  # no names or descriptions leave (decision 12)


def test_the_deadline_skips_holidays_and_suspensions(as_user):
    c = cast()
    api = as_user(c.owner)
    baseline, _ = _submitted(c, api)
    first_working_day = baseline.submitted_at.astimezone(DHAKA).date() + timedelta(days=1)
    while first_working_day.weekday() in (4, 5):
        first_working_day += timedelta(days=1)

    Holiday.objects.create(date=first_working_day, name_bn="ছুটি", name_en="Holiday")
    SlaSuspension.objects.create(
        scope_department=c.category.department,
        starts_on=first_working_day + timedelta(days=30),
        ends_on=first_working_day + timedelta(days=30),
        reason="Outside the window: must not count",
        created_by=c.admin,
    )
    later, _ = _submitted(c, api, HTTP_IDEMPOTENCY_KEY=key())
    assert later.due_at.date() > baseline.due_at.date()

    # The next working day: the day after may be a Friday or Saturday, which a suspension
    # would not move.
    next_working_day = first_working_day + timedelta(days=1)
    while next_working_day.weekday() in (4, 5):
        next_working_day += timedelta(days=1)
    national = SlaSuspension.objects.create(
        starts_on=next_working_day,
        ends_on=next_working_day,
        reason="Internet shutdown",
        created_by=c.admin,
    )
    suspended, _ = _submitted(c, api)
    assert suspended.due_at.date() > later.due_at.date()
    assert national.pk


def test_the_same_key_returns_the_same_answer_and_submits_once(as_user):
    c = cast()
    api = as_user(c.owner)
    request = in_state(c, Status.DRAFT)
    k = key()
    first = act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)
    again = act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert again["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first
    assert AuditLog.objects.filter(request=request, action="request.submit").count() == 1


def test_a_key_reused_with_a_different_body_is_refused(as_user):
    c = cast()
    api = as_user(c.owner)
    request = in_state(c, Status.DRAFT)
    k = key()
    act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)
    other = act(api, request, "submit", {"confirm_duplicate": True}, HTTP_IDEMPOTENCY_KEY=k)
    assert other.status_code == 422
    assert error_code(other) == "IDEMPOTENCY_KEY_REUSED"


def test_keys_are_per_user(as_user):
    c = cast()
    k = key()
    mine = in_state(c, Status.DRAFT)
    assert act(as_user(c.owner), mine, "submit", HTTP_IDEMPOTENCY_KEY=k).status_code == 200
    theirs = factories.draft(owner=c.stranger, cat=c.category)
    response = act(as_user(c.stranger), theirs, "submit", HTTP_IDEMPOTENCY_KEY=k)
    assert response.status_code == 200
    assert response.json()["id"] == str(theirs.public_id)


def test_a_key_expires_after_a_day(as_user):
    c = cast()
    api = as_user(c.owner)
    request = in_state(c, Status.DRAFT)
    k = key()
    act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE idempotency_record SET created_at = now() - interval '25 hours' WHERE key = %s",
            [k],
        )
    late = act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)
    assert error_code(late) == "INVALID_TRANSITION"  # judged afresh: already submitted


def test_expired_keys_are_purged_with_what_they_stored(as_user, settings):
    from apps.common import idempotency
    from apps.common.models import IdempotencyRecord

    c = cast()
    api = as_user(c.owner)
    old, fresh = key(), key()
    act(api, in_state(c, Status.DRAFT), "submit", HTTP_IDEMPOTENCY_KEY=old)
    act(
        api,
        factories.draft(owner=c.owner, cat=c.category, title="Other"),
        "submit",
        HTTP_IDEMPOTENCY_KEY=fresh,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE idempotency_record SET created_at = now() - interval '25 hours' WHERE key = %s",
            [old],
        )

    assert idempotency.purge_expired() == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == [fresh]
    schedule = settings.CELERY_BEAT_SCHEDULE["purge-idempotency-records"]
    assert schedule["task"] == "apps.common.tasks.purge_idempotency_records"


@pytest.mark.parametrize("header", [None, "short", "has space in it", "x" * 65])
def test_submit_needs_a_well_formed_key(as_user, header):
    c = cast()
    request = in_state(c, Status.DRAFT)
    headers = {} if header is None else {"HTTP_IDEMPOTENCY_KEY": header}
    response = as_user(c.owner).post(
        f"/api/v1/requests/{request.public_id}/actions/submit", {}, format="json", **headers
    )
    assert response.status_code == 400
    assert error_code(response) == "IDEMPOTENCY_KEY_REQUIRED"


def test_a_refused_submit_is_not_remembered(as_user):
    """Only successes are stored: fixing the problem and retrying with the same key works."""
    c = cast()
    api = as_user(c.owner)
    request = in_state(c, Status.DRAFT)
    c.category.is_active = False
    c.category.save()
    k = key()
    assert error_code(act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k)) == "CATEGORY_INACTIVE"
    c.category.is_active = True
    c.category.save()
    assert act(api, request, "submit", HTTP_IDEMPOTENCY_KEY=k).status_code == 200


def test_the_same_request_twice_asks_before_submitting(as_user):
    c = cast()
    api = as_user(c.owner)
    first, _ = _submitted(c, api)
    twin = factories.draft(owner=c.owner, cat=c.category, title=first.title)  # same content

    prompt = act(api, twin, "submit")
    assert prompt.status_code == 409
    assert error_code(prompt) == "POSSIBLE_DUPLICATE"
    assert prompt.json()["error"]["fields"]["tracking_no"] == first.tracking_no
    twin.refresh_from_db()
    assert twin.status == Status.DRAFT and twin.tracking_no is None

    confirmed = act(api, twin, "submit", {"confirm_duplicate": True})
    assert confirmed.status_code == 200


def test_different_requests_are_not_duplicates(as_user):
    c = cast()
    api = as_user(c.owner)
    first, _ = _submitted(c, api)
    other = factories.draft(
        owner=c.owner, cat=c.category, title=first.title, description="For my second child."
    )
    assert act(api, other, "submit").status_code == 200


def test_an_old_twin_is_not_a_duplicate(as_user):
    c = cast()
    api = as_user(c.owner)
    first, _ = _submitted(c, api)
    ServiceRequest.objects.filter(pk=first.pk).update(
        submitted_at=first.submitted_at - timedelta(minutes=11),
        sla_started_at=first.submitted_at - timedelta(minutes=11),
    )
    twin = factories.draft(owner=c.owner, cat=c.category, title=first.title)
    assert act(api, twin, "submit").status_code == 200


def test_an_unverified_phone_may_submit_one_request(as_user):
    """Degraded registration: if SMS is down, a citizen can still file once."""
    c = cast()
    citizen = factories.citizen()  # phone not verified
    api = as_user(citizen)
    first = factories.draft(owner=citizen, cat=c.category)
    second = factories.draft(owner=citizen, cat=c.category, title="Another")
    assert act(api, first, "submit").status_code == 200
    refused = act(api, second, "submit")
    assert refused.status_code == 403
    assert error_code(refused) == "PHONE_NOT_VERIFIED"


def test_a_refused_submit_uses_no_tracking_number(as_user):
    c = cast()
    api = as_user(c.owner)
    first, _ = _submitted(c, api)
    twin = factories.draft(owner=c.owner, cat=c.category, title=first.title)
    assert error_code(act(api, twin, "submit")) == "POSSIBLE_DUPLICATE"
    third = factories.draft(owner=c.owner, cat=c.category, title="Something else")
    act(api, third, "submit")
    third.refresh_from_db()
    serial = lambda number: int(number.split("-")[1])  # noqa: E731
    assert serial(third.tracking_no) == serial(first.tracking_no) + 1


def test_submitting_a_service_that_was_withdrawn(as_user):
    c = cast()
    request = factories.draft(owner=c.owner, cat=c.category)
    c.category.is_active = False
    c.category.save()
    assert error_code(act(as_user(c.owner), request, "submit")) == "CATEGORY_INACTIVE"


def test_create_then_submit_through_the_api(as_user):
    c = cast()
    api = as_user(c.owner)
    created = api.post("/api/v1/requests", draft_body(c.category), format="json")
    assert created.status_code == 201
    assert created.json()["status"] == Status.DRAFT
    request = ServiceRequest.objects.get(public_id=created.json()["id"])
    assert act(api, request, "submit").json()["status"] == Status.SUBMITTED
