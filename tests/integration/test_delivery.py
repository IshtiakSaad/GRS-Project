from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications import delivery, providers
from apps.notifications import services as notifications
from apps.notifications.models import DeliveryStatus, DemoSms, Notification
from tests import factories

pytestmark = pytest.mark.django_db


def _queued(template="password_changed", **kw):
    return notifications.queue(factories.citizen(preferred_language="en"), template, {}, **kw)


def test_sends_in_the_recipients_language_and_records_the_result():
    n = _queued()
    assert delivery.deliver(n.pk, n.created_at) == DeliveryStatus.SENT
    n.refresh_from_db()
    assert n.status == DeliveryStatus.SENT
    assert n.sent_at is not None
    assert n.lease_token is None
    assert n.provider_message_id.startswith("fake-")
    assert DemoSms.objects.get().body.startswith("Your password was changed")


def test_a_row_is_delivered_once_even_if_enqueued_twice():
    n = _queued()
    assert delivery.deliver(n.pk, n.created_at) == DeliveryStatus.SENT
    assert delivery.deliver(n.pk, n.created_at) == "skipped"
    assert DemoSms.objects.count() == 1


def test_a_leased_row_is_left_to_its_holder():
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(
        status=DeliveryStatus.LEASED,
        lease_token="00000000-0000-0000-0000-000000000001",
        leased_until=timezone.now() + timedelta(minutes=5),
    )
    assert delivery.deliver(n.pk, n.created_at) == "skipped"


def test_provider_failure_schedules_a_retry_with_backoff(monkeypatch):
    def down(phone, body):
        raise providers.ProviderError("gateway timeout")

    monkeypatch.setattr(providers, "send_sms", down)
    n = _queued()
    before = timezone.now()
    assert delivery.deliver(n.pk, n.created_at) == DeliveryStatus.PENDING
    n.refresh_from_db()
    assert n.attempts == 1
    assert n.last_error == "gateway timeout"
    assert n.lease_token is None
    # First retry: somewhere in the next 60 s (full jitter), so retries do not arrive together.
    assert before - timedelta(seconds=1) <= n.next_attempt_at <= before + timedelta(seconds=61)


def test_gives_up_after_the_attempt_cap(monkeypatch):
    def down(phone, body):
        raise providers.ProviderError("gateway timeout")

    monkeypatch.setattr(providers, "send_sms", down)
    n = _queued()
    Notification.objects.filter(pk=n.pk).update(attempts=7)
    assert delivery.deliver(n.pk, n.created_at) == DeliveryStatus.FAILED


def test_expired_messages_are_not_sent():
    n = _queued("otp", expires_in=timedelta(minutes=10))
    Notification.objects.filter(pk=n.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert delivery.deliver(n.pk, n.created_at) == DeliveryStatus.EXPIRED
    assert not DemoSms.objects.exists()
    assert Notification.objects.get(pk=n.pk).payload == {"erased": True}


def test_backoff_grows_and_is_capped():
    ceilings = [30 * 2**a for a in range(1, 8)]
    for attempts, ceiling in zip(range(1, 8), ceilings, strict=True):
        assert delivery.backoff(attempts).total_seconds() <= min(ceiling, 1800)


def test_a_broker_outage_does_not_fail_the_caller(monkeypatch, django_capture_on_commit_callbacks):
    from apps.notifications import tasks

    def broker_down(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(tasks.deliver, "delay", broker_down)
    with django_capture_on_commit_callbacks(execute=True):
        n = _queued()
    assert Notification.objects.get(pk=n.pk).status == DeliveryStatus.PENDING  # kept for later


def test_the_fake_sms_provider_refuses_to_run_outside_demo_mode(settings):
    """Otherwise real people's codes would sit in a table, unsent."""
    settings.DEMO_MODE = False
    with pytest.raises(providers.ProviderError):
        providers.send_sms("+8801712345678", "Your code is 123456")
    assert not DemoSms.objects.exists()
