from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications import services as notifications
from apps.notifications import sweeper, tasks
from apps.notifications.models import MAX_ATTEMPTS, DeliveryStatus, Kind, Notification
from tests import factories

pytestmark = pytest.mark.django_db


def _queued(template="password_changed", age=timedelta(minutes=2), **kw):
    n = notifications.queue(factories.citizen(), template, {}, **kw)
    Notification.objects.filter(pk=n.pk).update(next_attempt_at=timezone.now() - age)
    return Notification.objects.get(pk=n.pk)


@pytest.fixture
def enqueued(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.deliver, "delay", lambda *args: calls.append(args))
    return calls


def test_a_row_the_broker_lost_is_enqueued_again(enqueued):
    n = _queued()
    assert sweeper.sweep()["enqueued"] == 1
    assert enqueued == [(n.pk, n.created_at.isoformat())]
    assert Notification.objects.get(pk=n.pk).enqueued_at is not None


def test_an_enqueued_row_is_not_enqueued_again_right_away(enqueued):
    _queued()
    sweeper.sweep()
    assert sweeper.sweep()["enqueued"] == 0
    assert len(enqueued) == 1


def test_it_asks_again_when_the_queue_has_sat_on_a_row_too_long(enqueued):
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(enqueued_at=timezone.now() - timedelta(minutes=6))
    assert sweeper.sweep()["enqueued"] == 1


def test_a_fresh_row_is_left_to_the_fast_path(enqueued):
    _queued(age=timedelta(seconds=0))
    assert sweeper.sweep()["enqueued"] == 0


def test_a_retry_waits_for_its_backoff(enqueued):
    _queued(age=-timedelta(minutes=10))  # next attempt is in the future
    assert sweeper.sweep()["enqueued"] == 0


def test_a_dead_workers_lease_is_recovered_and_counted(enqueued):
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(
        status=DeliveryStatus.LEASED,
        lease_token="00000000-0000-0000-0000-000000000001",
        leased_until=timezone.now() - timedelta(seconds=1),
    )
    assert sweeper.recover_leases() == 1
    n.refresh_from_db()
    assert (n.status, n.attempts, n.lease_token) == (DeliveryStatus.PENDING, 1, None)


def test_a_message_that_keeps_killing_workers_stops_at_the_cap(enqueued):
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(
        status=DeliveryStatus.LEASED,
        attempts=MAX_ATTEMPTS - 1,
        lease_token="00000000-0000-0000-0000-000000000001",
        leased_until=timezone.now() - timedelta(seconds=1),
    )
    sweeper.recover_leases()
    assert Notification.objects.get(pk=n.pk).status == DeliveryStatus.FAILED


def test_a_live_lease_is_left_alone(enqueued):
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(
        status=DeliveryStatus.LEASED,
        lease_token="00000000-0000-0000-0000-000000000001",
        leased_until=timezone.now() + timedelta(minutes=5),
    )
    assert sweeper.recover_leases() == 0


def test_stale_status_messages_expire(enqueued):
    n = _queued("request_started", kind=Kind.STATUS, expires_in=timedelta(hours=72))
    Notification.objects.filter(pk=n.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    result = sweeper.sweep()
    assert (result["expired"], result["enqueued"]) == (1, 0)
    assert Notification.objects.get(pk=n.pk).status == DeliveryStatus.EXPIRED


def test_the_broker_still_down_leaves_rows_for_next_time(monkeypatch):
    def down(*args):
        raise ConnectionError("redis down")

    monkeypatch.setattr(tasks.deliver, "delay", down)
    _queued()
    assert sweeper.sweep()["enqueued"] == 0


def test_request_updates_also_go_by_email_once_verified():
    plain = factories.citizen(email="a@example.org")
    verified = factories.citizen(email="b@example.org", email_verified_at=timezone.now())
    for user, channels in [(plain, ["SMS"]), (verified, ["SMS", "EMAIL"])]:
        sent = notifications.notify(user, "request_started", {"tracking_no": "X"}, kind=Kind.STATUS)
        assert [n.channel for n in sent] == channels


def test_request_update_emails_carry_the_tracking_number_as_subject():
    from apps.notifications.templates import render

    assert render("request_resolved", "en", {"tracking_no": "GRS-1"})[0] == "Request GRS-1"
    assert render("otp", "en", {"code": "1"})[0] == ""
