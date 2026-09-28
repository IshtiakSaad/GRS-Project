import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_creates_verified_synthetic_citizens_once(settings):
    settings.DEMO_MODE = True
    call_command("seed_load_users", 3)
    call_command("seed_load_users", 3)  # idempotent
    users = User.objects.filter(phone__startswith="+8801099")
    assert users.count() == 3
    assert all(u.phone_verified_at and u.check_password("demo-password-2026") for u in users)


def test_refuses_outside_demo_mode(settings):
    settings.DEMO_MODE = False
    with pytest.raises(CommandError):
        call_command("seed_load_users", 1)
