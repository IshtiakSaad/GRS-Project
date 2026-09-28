from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Category, Holiday, SlaSuspension
from apps.service_requests.models import ServiceRequest, Status
from apps.sla import services as sla
from apps.sla.calendar import DHAKA
from apps.sla.tasks import recompute_due_dates
from tests import factories

from ..auth.helpers import error_code
from ..requests.helpers import cast, in_state

pytestmark = pytest.mark.django_db

ADMIN_READS = [
    "/api/v1/admin/departments",
    "/api/v1/admin/categories",
    "/api/v1/admin/holidays",
    "/api/v1/admin/sla-suspensions",
    "/api/v1/admin/users",
    "/api/v1/admin/stats",
]


@pytest.mark.parametrize("path", ADMIN_READS)
@pytest.mark.parametrize("who", ["owner", "assigned"])
def test_only_administrators(as_user, path, who):
    c = cast()
    assert as_user(c.by_name(who)).get(path).status_code == 403


@pytest.mark.parametrize("path", ADMIN_READS)
def test_administrators_need_their_second_step(as_user, path):
    c = cast()
    assert as_user(c.admin, mfa=False).get(path).status_code == 403
    assert as_user(c.admin).get(path).status_code == 200


@pytest.fixture
def committed(monkeypatch, django_capture_on_commit_callbacks):
    """`with committed(): ...` runs what the block schedules for after commit, as a real commit
    would. Recompute takes its broker-down path, so it runs inline, inside the test."""

    def fail(**_scope):
        raise ConnectionError("broker down")

    monkeypatch.setattr(recompute_due_dates, "delay", fail)
    return lambda: django_capture_on_commit_callbacks(execute=True)


# --- departments and categories ---------------------------------------------------------------


def test_departments(as_user):
    c = cast()
    api = as_user(c.admin)
    body = {"code": "PASSPORT", "name_bn": "পাসপোর্ট", "name_en": "Passport"}
    assert api.post("/api/v1/admin/departments", body, format="json").status_code == 201
    assert error_code(api.post("/api/v1/admin/departments", body, format="json")) == "CODE_IN_USE"
    patched = api.patch("/api/v1/admin/departments/PASSPORT", {"is_active": False}, format="json")
    assert patched.json()["is_active"] is False
    audit = AuditLog.objects.get(action="admin.department.update")
    assert (audit.data["before"]["is_active"], audit.data["after"]["is_active"]) == (
        "True",
        "False",
    )
    assert api.patch("/api/v1/admin/departments/NOPE", {}, format="json").status_code == 404


def test_codes_are_upper_case_identifiers(as_user):
    c = cast()
    body = {"code": "has space", "name_bn": "x", "name_en": "x"}
    response = as_user(c.admin).post("/api/v1/admin/departments", body, format="json")
    assert "code" in response.json()["error"]["fields"]


def test_categories(as_user):
    c = cast()
    api = as_user(c.admin)
    body = {
        "department": c.category.department.code,
        "code": "TRADE_LICENCE",
        "name_bn": "ট্রেড লাইসেন্স",
        "name_en": "Trade licence",
        "target_working_days": 10,
    }
    created = api.post("/api/v1/admin/categories", body, format="json")
    assert created.status_code == 201
    assert AuditLog.objects.filter(action="admin.category.create").exists()

    unknown = api.post(
        "/api/v1/admin/categories", {**body, "code": "OTHER", "department": "NOPE"}, format="json"
    )
    assert "department" in unknown.json()["error"]["fields"]

    closed = api.patch(
        "/api/v1/admin/categories/TRADE_LICENCE", {"is_active": False}, format="json"
    )
    assert closed.json()["is_active"] is False
    public = [row["code"] for row in api.get("/api/v1/categories").json()]
    assert "TRADE_LICENCE" not in public  # withdrawn from citizens at once
    listed = [row["code"] for row in api.get("/api/v1/admin/categories").json()]
    assert "TRADE_LICENCE" in listed  # admins still see it


def test_a_category_never_changes_department(as_user):
    c = cast()
    other = factories.department()
    response = as_user(c.admin).patch(
        f"/api/v1/admin/categories/{c.category.code}", {"department": other.code}, format="json"
    )
    assert response.status_code == 400
    assert "department" in response.json()["error"]["fields"]
    c.category.refresh_from_db()
    assert c.category.department_id != other.pk


def test_a_new_target_moves_the_open_deadlines_of_that_category_only(as_user, committed):
    c = cast()
    open_request = in_state(c, Status.IN_PROGRESS)
    closed_request = in_state(c, Status.RESOLVED)
    elsewhere = in_state(cast(), Status.IN_PROGRESS)
    before = {r.pk: r.due_at for r in (open_request, closed_request, elsewhere)}

    with committed():
        as_user(c.admin).patch(
            f"/api/v1/admin/categories/{c.category.code}",
            {"target_working_days": 20},
            format="json",
        )

    for r in (open_request, closed_request, elsewhere):
        r.refresh_from_db()
    assert open_request.due_at == sla.compute_due_at(open_request)
    assert open_request.due_at > before[open_request.pk]
    assert open_request.version == 2  # the ETag moves with the deadline
    assert closed_request.due_at == before[closed_request.pk]
    assert elsewhere.due_at == before[elsewhere.pk]


# --- holidays and suspensions -----------------------------------------------------------------


def _next_working_day(after: date) -> date:
    day = after + timedelta(days=1)
    while day.weekday() in (4, 5):
        day += timedelta(days=1)
    return day


def test_a_late_announced_holiday_moves_open_deadlines(as_user, committed):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    sla.recompute_open(category_id=c.category.pk)  # start from the computed deadline
    request.refresh_from_db()
    before = request.due_at
    holiday = _next_working_day(timezone.now().astimezone(DHAKA).date())

    api = as_user(c.admin)
    body = {"date": str(holiday), "name_bn": "ঈদ", "name_en": "Eid"}
    with committed():
        assert api.post("/api/v1/admin/holidays", body, format="json").status_code == 201
    request.refresh_from_db()
    assert request.due_at > before  # one more working day to count

    assert error_code(api.post("/api/v1/admin/holidays", body, format="json")) == "HOLIDAY_EXISTS"
    with committed():
        assert api.delete(f"/api/v1/admin/holidays/{holiday}").status_code == 204
    request.refresh_from_db()
    assert request.due_at == before
    assert not Holiday.objects.filter(date=holiday).exists()
    assert api.delete("/api/v1/admin/holidays/not-a-date").status_code == 404


def test_a_department_suspension_moves_only_that_departments_deadlines(as_user, committed):
    c = cast()
    mine = in_state(c, Status.ASSIGNED)
    other = in_state(cast(), Status.ASSIGNED)
    sla.recompute_open()
    mine.refresh_from_db()
    other.refresh_from_db()
    before = {mine.pk: mine.due_at, other.pk: other.due_at}
    today = timezone.now().astimezone(DHAKA).date()

    body = {
        "department": c.category.department.code,
        "starts_on": str(today),
        "ends_on": str(today + timedelta(days=14)),
        "reason": "Flooding: office closed.",
    }
    api = as_user(c.admin)
    with committed():
        created = api.post("/api/v1/admin/sla-suspensions", body, format="json")
    assert created.status_code == 201
    mine.refresh_from_db()
    other.refresh_from_db()
    assert mine.due_at > before[mine.pk]
    assert other.due_at == before[other.pk]

    with committed():
        deleted = api.delete(f"/api/v1/admin/sla-suspensions/{created.json()['id']}")
    assert deleted.status_code == 204
    mine.refresh_from_db()
    assert mine.due_at == before[mine.pk]
    assert not SlaSuspension.objects.exists()


def test_a_suspension_ends_after_it_starts(as_user):
    c = cast()
    body = {"starts_on": "2026-10-10", "ends_on": "2026-10-01", "reason": "Wrong way round."}
    response = as_user(c.admin).post("/api/v1/admin/sla-suspensions", body, format="json")
    assert "ends_on" in response.json()["error"]["fields"]


def test_recompute_in_batches_touches_only_open_requests():
    c = cast()
    requests = [in_state(c, Status.SUBMITTED) for _ in range(5)]
    done = in_state(c, Status.RESOLVED)
    ServiceRequest.objects.filter(pk__in=[r.pk for r in requests]).update(
        due_at=timezone.now() + timedelta(days=90)
    )
    original = sla.RECOMPUTE_BATCH
    sla.RECOMPUTE_BATCH = 2
    try:
        assert sla.recompute_open(category_id=c.category.pk) == 5
    finally:
        sla.RECOMPUTE_BATCH = original
    for r in requests:
        r.refresh_from_db()
        assert r.due_at == sla.compute_due_at(r)
    done_before = done.due_at
    done.refresh_from_db()
    assert done.due_at == done_before
    assert Category.objects.filter(pk=c.category.pk).exists()


def test_with_the_broker_up_the_recompute_is_queued_for_the_worker(
    as_user, monkeypatch, django_capture_on_commit_callbacks
):
    c = cast()
    queued = []
    monkeypatch.setattr(recompute_due_dates, "delay", lambda **scope: queued.append(scope))
    api = as_user(c.admin)
    dept = c.category.department
    with django_capture_on_commit_callbacks(execute=True):
        api.post(
            "/api/v1/admin/holidays",
            {"date": "2026-12-16", "name_bn": "বিজয় দিবস", "name_en": "Victory Day"},
            format="json",
        )
        api.post(
            "/api/v1/admin/sla-suspensions",
            {
                "department": dept.code,
                "starts_on": "2026-11-01",
                "ends_on": "2026-11-02",
                "reason": "Strike.",
            },
            format="json",
        )
        api.patch(
            f"/api/v1/admin/categories/{c.category.code}",
            {"target_working_days": 9},
            format="json",
        )
        api.patch(f"/api/v1/admin/categories/{c.category.code}", {"name_en": "X"}, format="json")
    assert queued == [{}, {"department_id": dept.pk}, {"category_id": c.category.pk}]
