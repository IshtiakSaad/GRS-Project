import os
import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import sessions
from apps.audit.models import AuditLog
from apps.service_requests import services
from apps.service_requests.models import Priority, ServiceRequest, Status
from tests import factories

from .helpers import cast, in_state, key

pytestmark = pytest.mark.django_db


def _waiting(c, **kw):
    return factories.submitted(owner=c.owner, cat=c.category, **kw)


def test_the_queue_is_most_urgent_then_earliest_deadline_then_first_come(as_user):
    c = cast()
    now = timezone.now()
    normal_late = _waiting(c, due_at=now + timedelta(days=9))
    normal_soon = _waiting(c, due_at=now + timedelta(days=2))
    urgent = _waiting(c, priority=Priority.URGENT, due_at=now + timedelta(days=20))
    tie_first = _waiting(c, due_at=now + timedelta(days=5), submitted_at=now - timedelta(hours=2))
    tie_second = _waiting(c, due_at=now + timedelta(days=5), submitted_at=now - timedelta(hours=1))
    factories.submitted()  # another department's

    body = as_user(c.colleague).get("/api/v1/queue").json()
    order = [row["id"] for row in body["requests"]]
    expected = [urgent, normal_soon, tie_first, tie_second, normal_late]
    assert order == [str(r.public_id) for r in expected]
    assert body["waiting"] == 5


def test_claim_next_takes_the_top_of_the_queue(as_user):
    c = cast()
    _waiting(c)
    top = _waiting(c, priority=Priority.HIGH)
    response = as_user(c.colleague).post("/api/v1/queue/claim-next")
    assert response.status_code == 200
    assert response.json()["id"] == str(top.public_id)
    top.refresh_from_db()
    assert (top.status, top.assigned_officer_id) == (Status.ASSIGNED, c.colleague.pk)
    assert AuditLog.objects.filter(request=top, action="request.claim_next").exists()


def test_an_empty_queue_answers_204(as_user):
    c = cast()
    in_state(c, Status.ASSIGNED)  # not waiting
    assert as_user(c.colleague).post("/api/v1/queue/claim-next").status_code == 204


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_only_officers_have_a_queue(as_user, who):
    c = cast()
    api = as_user(c.by_name(who))
    assert api.get("/api/v1/queue").status_code == 403
    assert api.post("/api/v1/queue/claim-next").status_code == 403


def test_the_queue_is_one_departments(as_user):
    c = cast()
    _waiting(c)
    assert as_user(c.outsider).post("/api/v1/queue/claim-next").status_code == 204


# --- concurrency: real parallel sessions, committed data ---------------------------------------


def _in_parallel(n, work):
    """Run work(i) in n threads that start together. Each thread has its own connection, as
    the API's database role, so its privileges and timeouts are the production ones."""
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def run(i):
        connection.settings_dict = {
            **connection.settings_dict,
            "USER": "grs_api",
            "PASSWORD": os.environ["GRS_API_PASSWORD"],
        }
        try:
            barrier.wait(timeout=10)
            results[i] = work(i)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    return results


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_parallel_officers_each_get_a_different_request():
    c = cast()
    for _ in range(6):
        _waiting(c)
    officers = [c.assigned, c.colleague] + [
        factories.officer(c.category.department) for _ in range(6)
    ]

    claimed = _in_parallel(len(officers), lambda i: services.claim_next(officers[i]))

    got = [r.pk for r in claimed if r is not None]
    assert len(got) == 6 == len(set(got))  # every request once, nobody got the same one
    assert claimed.count(None) == 2  # the rest found the queue empty; nobody waited or failed
    assigned = ServiceRequest.objects.filter(status=Status.ASSIGNED)
    assert assigned.count() == 6
    assert len({r.assigned_officer_id for r in assigned}) == 6


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_claim_skips_a_request_another_officer_is_taking(connect_as):
    """Not just different requests: nobody waits. With the top request locked by another
    session, claim-next returns the next one at once instead of queueing behind the lock."""
    import time

    c = cast()
    top = _waiting(c, priority=Priority.URGENT)
    second = _waiting(c)
    with connect_as() as other, other.transaction():
        other.execute("SELECT 1 FROM service_request WHERE id = %s FOR UPDATE", [top.pk])
        started = time.monotonic()
        claimed = services.claim_next(c.colleague)
        elapsed = time.monotonic() - started
    assert claimed.pk == second.pk
    assert elapsed < 1  # a blocking lock would wait for the other session (or lock_timeout)


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_a_double_tap_with_one_key_submits_once():
    c = cast()
    draft = factories.draft(owner=c.owner, cat=c.category)
    issued = sessions.start(c.owner, device_id=None, trust_mode="SHARED", mfa=False)
    k = key()

    def submit(_):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access}")
        return api.post(
            f"/api/v1/requests/{draft.public_id}/actions/submit",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=k,
        )

    first, second = _in_parallel(2, submit)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert AuditLog.objects.filter(request=draft, action="request.submit").count() == 1


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_racing_transitions_apply_one_at_a_time():
    """Officer resolves while the citizen withdraws: the row lock orders them; the loser gets a
    clean 409, never a half-applied change."""
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)

    def race(i):
        from apps.common.errors import AppError
        from apps.service_requests import transitions

        user, action, data = [
            (c.assigned, "resolve", {"note": "Done."}),
            (c.owner, "withdraw", {}),
        ][i]
        try:
            transitions.perform(user, request.public_id, action, data)
            return "ok"
        except AppError as exc:
            return exc.error_code

    outcomes = _in_parallel(2, race)
    assert sorted(outcomes) == ["INVALID_TRANSITION", "ok"]
    request.refresh_from_db()
    assert request.status in (Status.RESOLVED, Status.WITHDRAWN)
    assert request.version == 2
