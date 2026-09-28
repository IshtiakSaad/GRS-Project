"""Failure paths: forged input, races and a dead cache."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.accounts import services
from apps.accounts.apps import check_keys
from apps.accounts.hashers import Argon2idHasher
from apps.accounts.models import User
from apps.notifications.models import Notification
from tests import factories

from .helpers import PASSWORD, error_code

pytestmark = pytest.mark.django_db


def test_register_race_on_one_number_creates_one_account(monkeypatch):
    winner = factories.citizen()
    # The other request committed between our lookup and our insert.
    monkeypatch.setattr(services, "_by_phone", lambda phone: None)
    services.register(winner.phone, PASSWORD, "Racer", "bn")
    assert User.objects.filter(phone=winner.phone).count() == 1
    assert Notification.objects.filter(recipient=winner, template="register_attempt").exists()


def test_register_warning_is_skipped_when_the_cache_is_down(monkeypatch):
    owner = factories.citizen()

    def down(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr("django.core.cache.cache.add", down)
    services.register(owner.phone, PASSWORD, "Someone", "bn")  # must not raise
    assert not Notification.objects.filter(recipient=owner).exists()


def test_deactivated_owner_is_not_warned():
    owner = factories.citizen(is_active=False)
    services.register(owner.phone, PASSWORD, "Someone", "bn")
    assert not Notification.objects.filter(recipient=owner).exists()


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", None, 42])
def test_forged_device_tokens_fall_back_to_the_shared_bucket(token):
    user = factories.citizen()
    assert services.read_device_token(token, user) is None


def test_garbage_second_factor_token(api):
    response = api.post(
        "/api/v1/auth/2fa/verify", {"mfa_token": "not-a-token", "code": "123456"}, format="json"
    )
    assert response.status_code == 401
    assert error_code(response) == "MFA_TOKEN_INVALID"


def test_wrong_code_at_enrolment_leaves_two_step_login_off(as_user):
    officer = factories.officer()
    client = as_user(officer)
    client.post("/api/v1/auth/2fa/setup")
    response = client.post(
        "/api/v1/auth/2fa/confirm", {"current_password": "pw", "code": "12345x"}, format="json"
    )
    assert error_code(response) == "INVALID_CODE"
    officer.refresh_from_db()
    assert officer.totp_enabled_at is None


@pytest.mark.parametrize("token", ["", "forged:token", "x" * 100])
def test_forged_email_tokens_are_refused(api, token):
    response = api.post("/api/v1/auth/email/verify", {"token": token}, format="json")
    assert response.status_code == 400


def test_setting_the_same_email_again_sends_nothing(as_user):
    user = factories.citizen(email="same@example.com")
    as_user(user).patch("/api/v1/me", {"email": "Same@Example.com"}, format="json")
    assert not Notification.objects.filter(template="verify_email").exists()


def test_password_change_is_throttled(as_user):
    client = as_user(factories.citizen())
    body = {"current_password": "wrong", "new_password": "a-new-long-passphrase"}
    for _ in range(5):
        client.post("/api/v1/me/password", body, format="json")
    assert client.post("/api/v1/me/password", body, format="json").status_code == 429


# --- configuration --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("JWT_ACTIVE_KID", "missing"),
        ("JWT_SIGNING_KEYS", {"t1": "short"}),
        ("FIELD_ENCRYPTION_KEYS", []),
        ("FIELD_ENCRYPTION_KEYS", ["not-a-fernet-key"]),
    ],
)
def test_refuses_to_start_with_weak_or_broken_keys(settings, setting, value):
    setattr(settings, setting, value)
    with pytest.raises(ImproperlyConfigured):
        check_keys()


def test_production_hasher_uses_the_benchmarked_parameters():
    encoded = Argon2idHasher().encode("a-long-demo-passphrase", Argon2idHasher().salt())
    assert encoded.startswith("argon2$argon2id$v=19$m=19456,t=2,p=1$")
    assert Argon2idHasher().verify("a-long-demo-passphrase", encoded)
    assert not Argon2idHasher().verify("wrong", encoded)
