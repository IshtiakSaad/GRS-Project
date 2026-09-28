from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit import services as audit
from apps.service_requests.models import ServiceRequest, SlaPause, Status
from tests import factories

from ..requests.helpers import cast, in_state

pytestmark = pytest.mark.django_db


def _set(request, **fields):
    ServiceRequest.objects.filter(pk=request.pk).update(**fields)
    request.refresh_from_db()
    return request


def _event(request, event_type, from_status):
    request.events.create(event_type=event_type, from_status=from_status, is_public=True)


@pytest.fixture
def world():
    """One department's month, built so every metric has a known answer."""
    c = cast()
    now = timezone.now()
    on_time = in_state(c, Status.RESOLVED)
    _set(on_time, resolved_at=on_time.submitted_at + timedelta(days=1))
    late = in_state(c, Status.RESOLVED)
    _set(
        late,
        resolved_at=late.submitted_at + timedelta(days=3),
        due_at=late.submitted_at + timedelta(days=2),
    )
    for r in (on_time, late):
        _event(r, "resolve", Status.IN_PROGRESS)
    _event(on_time, "reopen", Status.RESOLVED)  # reopened once, then resolved again

    rejected = in_state(c, Status.REJECTED)
    _event(rejected, "reject", Status.IN_PROGRESS)
    audit.record("request.reject", request=rejected, data={"late_rejection": True})

    withdrawn = in_state(c, Status.WITHDRAWN)
    _set(withdrawn, due_at=now - timedelta(hours=2), closed_at=now)

    overdue = in_state(c, Status.SUBMITTED)
    _set(overdue, due_at=now - timedelta(hours=1))

    paused = in_state(c, Status.IN_PROGRESS)
    _set(paused, info_request_count=1, reassignment_count=1)
    SlaPause.objects.create(
        request=paused,
        reason_code="OTHER",
        started_at=paused.submitted_at,
        ended_at=paused.submitted_at + timedelta(days=1),
    )

    old = in_state(c, Status.RESOLVED)
    _set(old, submitted_at=now - timedelta(days=60), sla_started_at=now - timedelta(days=60))
    factories.draft(owner=c.owner, cat=c.category)  # drafts are never counted
    return c


def _stats(api, query=""):
    response = api.get(f"/api/v1/admin/stats{query}")
    assert response.status_code == 200, response.content
    return response.json()


def test_each_metric_comes_with_its_counter_metrics(as_user, world):
    body = _stats(as_user(world.admin))
    totals = body["totals"]
    assert totals["counts"] == {
        "submitted": 6,  # the 60-day-old request is outside the default 30 days
        "open": 2,
        "overdue": 1,
        "resolved": 2,
        "rejected": 1,
        "withdrawn": 1,
    }
    assert totals["primary"] == {
        "on_time_resolution_rate": 0.5,
        "median_days_to_resolve": 2.0,
        "resolution_rate": round(2 / 6, 4),
        "resolved": 2,
    }
    counter = totals["counter"]
    assert counter["info_request_rate"] == round(1 / 6, 4)
    assert counter["median_days_paused"] == 1.0
    assert counter["rejection_rate"] == round(1 / 6, 4)
    assert counter["late_rejections"] == 1
    assert counter["reopen_rate_after_resolution"] == 0.5
    assert counter["reopen_rate_after_rejection"] == 0.0
    assert counter["reassignment_rate"] == round(1 / 6, 4)
    assert counter["withdrawn_after_deadline"] == 1

    [group] = body["groups"]
    assert group["group"]["code"] == world.category.department.code
    assert group["counts"] == totals["counts"]


def test_by_officer_is_throughput_per_person(as_user, world):
    body = _stats(as_user(world.admin), "?by=officer")
    by_code = {g["group"]["code"]: g for g in body["groups"]}
    assigned = by_code[str(world.assigned.public_id)]
    assert assigned["group"]["name"] == world.assigned.full_name
    assert assigned["primary"]["resolved"] == 2
    assert by_code[None]["counts"]["submitted"] == 2  # waiting and withdrawn: never assigned


def test_the_period_is_chosen_in_dhaka_dates(as_user, world):
    today = timezone.now().date()
    body = _stats(
        as_user(world.admin),
        f"?date_from={today - timedelta(days=90)}&date_to={today}",
    )
    assert body["totals"]["counts"]["submitted"] == 7


def test_bad_periods_are_refused(as_user):
    c = cast()
    api = as_user(c.admin)
    assert api.get("/api/v1/admin/stats?date_from=2026-05-01&date_to=2026-04-01").status_code == 400
    assert api.get("/api/v1/admin/stats?date_from=2024-01-01&date_to=2026-01-01").status_code == 400
    assert api.get("/api/v1/admin/stats?by=mood").status_code == 400


def test_an_empty_period(as_user):
    c = cast()
    body = _stats(as_user(c.admin))
    assert body["groups"] == []
    assert body["totals"]["counts"]["submitted"] == 0
    assert body["totals"]["primary"]["on_time_resolution_rate"] is None


# --- the all-requests list --------------------------------------------------------------------


def _ids(response):
    return {row["id"] for row in response.json()["results"]}


def test_administrators_filter_every_request(as_user):
    c = cast()
    mine = in_state(c, Status.ASSIGNED)
    overdue = _set(in_state(c, Status.SUBMITTED), due_at=timezone.now() - timedelta(hours=1))
    elsewhere = in_state(cast(), Status.SUBMITTED)
    api = as_user(c.admin)
    base = "/api/v1/requests"
    ids = lambda *rs: {str(r.public_id) for r in rs}  # noqa: E731
    assert _ids(api.get(f"{base}?category={c.category.code}")) == ids(mine, overdue)
    assert _ids(api.get(f"{base}?department={elsewhere.department.code}")) == ids(elsewhere)
    assert _ids(api.get(f"{base}?officer={c.assigned.public_id}")) == ids(mine)
    assert ids(overdue) <= _ids(api.get(f"{base}?overdue=true"))
    assert str(mine.public_id) not in _ids(api.get(f"{base}?overdue=true"))
    assert api.get(f"{base}?officer=not-a-uuid").status_code == 400


def test_filters_never_widen_an_officers_scope(as_user):
    c = cast()
    elsewhere = in_state(cast(), Status.SUBMITTED)
    response = as_user(c.colleague).get(f"/api/v1/requests?department={elsewhere.department.code}")
    assert _ids(response) == set()
