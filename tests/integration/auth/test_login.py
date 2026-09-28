from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import throttle
from apps.accounts.models import LoginThrottle, RefreshSession, TrustMode
from apps.audit.models import AuditLog
from tests import factories

from .helpers import PASSWORD, error_code

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/login"


def _login(api, phone, password=PASSWORD, **extra):
    return api.post(URL, {"phone": phone, "password": password, **extra}, format="json")


@pytest.fixture
def citizen():
    user = factories.citizen()
    user.set_password(PASSWORD)
    user.save()
    return user


def test_login_returns_tokens_that_open_the_api(api, citizen):
    response = _login(api, citizen.phone)
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is False
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    me = api.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["phone"] == citizen.phone
    assert "password" not in me.json()

    citizen.refresh_from_db()
    assert citizen.last_login is not None
    assert AuditLog.objects.filter(action="auth.login", actor=citizen).exists()


def test_wrong_password_and_unknown_phone_look_identical(api, citizen):
    wrong = _login(api, citizen.phone, "not-the-password")
    unknown = _login(api, "01099999999", "not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert error_code(wrong) == error_code(unknown) == "INVALID_CREDENTIALS"


def test_inactive_account_cannot_log_in_even_with_the_right_password(api, citizen):
    citizen.is_active = False
    citizen.save()
    assert error_code(_login(api, citizen.phone)) == "INVALID_CREDENTIALS"


def test_citizen_sessions_are_short_on_shared_devices_unless_the_phone_is_theirs(api, citizen):
    _login(api, citizen.phone)
    _login(api, citizen.phone, trust_mode="PERSONAL")
    shared, personal = RefreshSession.objects.order_by("id")
    assert shared.trust_mode == TrustMode.SHARED
    assert shared.absolute_expires_at - shared.created_at < timedelta(hours=9)
    assert personal.trust_mode == TrustMode.PERSONAL
    assert personal.absolute_expires_at - personal.created_at > timedelta(days=89)


def test_staff_get_office_day_sessions_whatever_they_ask_for(api):
    officer = factories.officer()
    officer.set_password(PASSWORD)
    officer.save()
    _login(api, officer.phone, trust_mode="PERSONAL")
    session = RefreshSession.objects.get()
    assert session.trust_mode == TrustMode.STAFF
    assert session.absolute_expires_at - session.created_at < timedelta(hours=13)


# --- throttling -------------------------------------------------------------------------------


def test_five_failures_then_a_growing_delay(api, citizen):
    for _ in range(throttle.FREE_FAILURES - 1):
        assert _login(api, citizen.phone, "wrong").status_code == 401
    assert _login(api, citizen.phone, "wrong").status_code == 401  # the 5th: now delayed
    delayed = _login(api, citizen.phone)  # even the right password waits
    assert delayed.status_code == 429
    assert error_code(delayed) == "LOGIN_DELAYED"
    assert 55 <= int(delayed["Retry-After"]) <= 60


def test_delay_doubles_and_is_capped():
    assert [throttle.delay_after(n) for n in range(4, 11)] == [0, 60, 120, 240, 480, 900, 900]


def test_attacker_on_unknown_devices_cannot_delay_the_owners_known_device(api, citizen):
    device_token = _login(api, citizen.phone).json()["device_token"]
    for _ in range(8):
        _login(api, citizen.phone, "wrong")  # no device token: the shared "unknown" bucket
    assert _login(api, citizen.phone).status_code == 429
    known = _login(api, citizen.phone, device_token=device_token)
    assert known.status_code == 200


def test_a_device_token_is_bound_to_its_account(api, citizen):
    other = factories.citizen()
    other.set_password(PASSWORD)
    other.save()
    stolen = _login(api, other.phone).json()["device_token"]
    for _ in range(5):
        _login(api, citizen.phone, "wrong")
    # Another account's device token does not open a separate bucket here.
    assert _login(api, citizen.phone, device_token=stolen).status_code == 429


def test_success_clears_the_bucket(api, citizen):
    for _ in range(3):
        _login(api, citizen.phone, "wrong")
    _login(api, citizen.phone)
    assert not LoginThrottle.objects.exists()


def test_unknown_numbers_are_delayed_on_the_same_schedule(api, citizen):
    for _ in range(5):
        _login(api, "01099999999", "wrong")
        _login(api, citizen.phone, "wrong")
    unknown = _login(api, "01099999999", "wrong")
    known = _login(api, citizen.phone, "wrong")
    assert unknown.status_code == known.status_code == 429


def test_failures_accumulate_in_one_row(citizen):
    for _ in range(7):
        throttle.record_failure(citizen, "unknown")
    row = LoginThrottle.objects.get()
    assert row.failures == 7
    assert row.next_allowed_at > timezone.now() + timedelta(minutes=3)
