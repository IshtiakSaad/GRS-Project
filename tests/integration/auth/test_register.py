from datetime import timedelta

import pytest
from django.contrib.auth.hashers import check_password
from django.db.models import F

from apps.accounts import otp
from apps.accounts.models import OtpChallenge, RefreshSession, User
from apps.notifications.models import DemoSms, Notification
from tests import factories

from .helpers import PASSWORD, deliver_all, error_code, sms_code

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/register"


def _register(api, phone="01000000001", password=PASSWORD, **extra):
    body = {"phone": phone, "password": password, "full_name": "  Rahima  Khatun ", **extra}
    return api.post(URL, body, format="json")


def test_register_then_verify_phone_by_sms(api):
    response = _register(api, phone="০১০০০০০০০০১")  # Bangla digits
    assert response.status_code == 202
    user = User.objects.get(phone="+8801000000001")
    assert user.full_name == "Rahima  Khatun"
    assert user.phone_verified_at is None
    assert check_password(PASSWORD, user.password)

    code = sms_code(api, "01000000001")
    verify = api.post(
        "/api/v1/auth/otp/verify", {"phone": "01000000001", "code": code}, format="json"
    )
    assert verify.status_code == 200
    user.refresh_from_db()
    assert user.phone_verified_at is not None


def test_the_right_code_logs_the_new_citizen_in(api):
    """No second screen asking for the password chosen a minute ago."""
    _register(api)
    code = sms_code(api, "01000000001")
    body = {"phone": "01000000001", "code": code, "trust_mode": "PERSONAL"}
    out = api.post("/api/v1/auth/otp/verify", body, format="json").json()
    assert out["mfa_required"] is False
    assert out["device_token"] and out["refresh"]
    session = RefreshSession.objects.get(user__phone="+8801000000001")
    assert session.trust_mode == "PERSONAL"

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {out['access']}")
    me = api.get("/api/v1/me").json()
    assert me["phone_verified"] is True


def test_confirming_from_the_profile_opens_no_second_session(api):
    _register(api)
    code = sms_code(api, "01000000001")
    body = {"phone": "01000000001", "code": code, "start_session": False}
    response = api.post("/api/v1/auth/otp/verify", body, format="json")
    assert response.status_code == 204
    assert User.objects.get().phone_verified_at is not None
    assert not RefreshSession.objects.exists()


def test_a_wrong_code_logs_no_one_in(api):
    _register(api)
    code = sms_code(api, "01000000001")
    wrong = "000000" if code != "000000" else "111111"
    body = {"phone": "01000000001", "code": wrong}
    assert api.post("/api/v1/auth/otp/verify", body, format="json").status_code == 400
    assert not RefreshSession.objects.exists()


def test_existing_number_gets_the_same_answer_and_its_owner_is_warned(api):
    owner = factories.citizen()
    fresh = _register(api, phone="01000000002")
    taken = _register(api, phone=owner.phone)
    assert taken.status_code == fresh.status_code == 202
    assert taken.json() == fresh.json()
    assert User.objects.filter(phone=owner.phone).count() == 1
    assert not check_password(PASSWORD, User.objects.get(pk=owner.pk).password)

    deliver_all()
    warning = DemoSms.objects.get(phone=owner.phone)
    assert "নিবন্ধনের চেষ্টা" in warning.body  # owner's language is Bangla by default


def test_owner_is_warned_at_most_once_an_hour(api):
    owner = factories.citizen()
    for _ in range(3):
        _register(api, phone=owner.phone)
    assert Notification.objects.filter(recipient=owner, template="register_attempt").count() == 1


def test_weak_password_is_refused_before_anything_is_created(api):
    response = _register(api, password="12345678")
    assert response.status_code == 400
    assert "password" in response.json()["error"]["fields"]
    assert not User.objects.exists()


@pytest.mark.parametrize("phone", ["01712345678", "12345", "not a phone"])
def test_numbers_outside_demo_range_are_refused(api, phone):
    response = _register(api, phone=phone)
    assert response.status_code == 400
    # The demo refuses real numbers, so its example must not be one.
    (message,) = response.json()["error"]["fields"]["phone"]
    assert "010" in message
    assert "017" not in message


@pytest.mark.parametrize("phone", ["01012345678", "12345"])
def test_outside_the_demo_the_example_is_a_real_number(api, settings, phone):
    settings.DEMO_MODE = False
    (message,) = _register(api, phone=phone).json()["error"]["fields"]["phone"]
    assert "01712345678" in message


def test_codes_pause_for_everyone_when_the_site_budget_is_spent(api, settings):
    """Asking for codes to many numbers (SMS pumping) stops at the hourly budget."""
    settings.SMS_CODES_HOURLY_CAP = 2
    owner = factories.citizen()
    assert _register(api, phone="01000000001").status_code == 202
    assert _register(api, phone="01000000002").status_code == 202

    refused = _register(api, phone="01000000003")
    assert refused.status_code == 429
    assert error_code(refused) == "RATE_LIMITED"
    assert refused.headers["Retry-After"]
    assert not User.objects.filter(phone="+8801000000003").exists()
    # The same answer for a number that has an account: the refusal reveals no one.
    assert error_code(_register(api, phone=owner.phone)) == "RATE_LIMITED"
    for route in ("otp/resend", "password/reset/request"):
        body = {"phone": owner.phone}
        response = api.post(f"/api/v1/auth/{route}", body, format="json")
        assert error_code(response) == "RATE_LIMITED", route
    assert OtpChallenge.objects.count() == 2

    _age_codes(61)
    assert _register(api, phone="01000000003").status_code == 202


def test_code_is_stored_only_as_an_hmac_and_erased_from_the_outbox_once_sent(api):
    _register(api)
    code = sms_code(api, "01000000001")
    challenge = OtpChallenge.objects.get()
    assert code not in challenge.code_hmac
    assert Notification.objects.get(template="otp").payload == {"erased": True}


def test_five_wrong_codes_burn_the_code(api):
    _register(api)
    code = sms_code(api, "01000000001")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.MAX_ATTEMPTS):
        body = {"phone": "01000000001", "code": wrong}
        assert api.post("/api/v1/auth/otp/verify", body, format="json").status_code == 400
    right = api.post(
        "/api/v1/auth/otp/verify", {"phone": "01000000001", "code": code}, format="json"
    )
    assert right.status_code == 400
    assert error_code(right) == "INVALID_CODE"


def _age_codes(minutes):
    OtpChallenge.objects.update(created_at=F("created_at") - timedelta(minutes=minutes))


def test_resend_has_a_cooldown_and_an_hourly_cap(api):
    _register(api)
    user = User.objects.get()
    body = {"phone": "01000000001"}
    for _ in range(4):
        assert api.post("/api/v1/auth/otp/resend", body, format="json").status_code == 202
    assert OtpChallenge.objects.count() == 1  # nothing new inside the 60 s cooldown

    _age_codes(2)
    assert otp.issue(user, "VERIFY_PHONE")
    _age_codes(2)
    assert otp.issue(user, "VERIFY_PHONE")
    _age_codes(2)
    assert not otp.issue(user, "VERIFY_PHONE")  # three in the last hour
    _age_codes(60)
    assert otp.issue(user, "VERIFY_PHONE")


def test_resend_for_unknown_or_verified_numbers_looks_the_same(api):
    verified = factories.citizen(phone_verified_at="2026-01-01T00:00Z")
    unknown = api.post("/api/v1/auth/otp/resend", {"phone": "01000000009"}, format="json")
    known = api.post("/api/v1/auth/otp/resend", {"phone": verified.phone}, format="json")
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert not OtpChallenge.objects.exists()


def test_messages_follow_the_language_the_citizen_registered_in(api):
    api.post(
        URL,
        {"phone": "01000000005", "password": PASSWORD, "full_name": "Rahim"},
        format="json",
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert User.objects.get().preferred_language == "en"
    assert sms_code(api, "01000000005")
    assert DemoSms.objects.get().body.startswith("Your verification code")
