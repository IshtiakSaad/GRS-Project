import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.service_requests.models import RequestEvent, ServiceRequest, Status

pytestmark = pytest.mark.django_db


def test_seed_shows_every_state_through_the_real_engine(settings, capsys):
    settings.DEMO_MODE = True
    call_command("seed_demo")

    states = set(ServiceRequest.objects.values_list("status", flat=True))
    assert states == set(Status.values)
    assert ServiceRequest.objects.filter(beneficiary_name__isnull=False).exists()
    assert ServiceRequest.objects.filter(reopen_count=1).exists()
    submitted = ServiceRequest.objects.exclude(status=Status.DRAFT).count()
    assert RequestEvent.objects.filter(event_type="submit").count() == submitted
    assert all(p.startswith("+88010") for p in User.objects.values_list("phone", flat=True))

    out = capsys.readouterr().out
    assert "otpauth://totp/" in out

    total = ServiceRequest.objects.count()
    call_command("seed_demo")  # a second run changes nothing
    assert ServiceRequest.objects.count() == total
    assert "already loaded" in capsys.readouterr().out


def test_seed_refuses_a_live_system(settings):
    settings.DEMO_MODE = False
    with pytest.raises(CommandError, match="DEMO_MODE"):
        call_command("seed_demo")
    assert not ServiceRequest.objects.exists()
