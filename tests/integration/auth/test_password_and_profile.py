from datetime import timedelta

import pytest
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.utils import timezone

from apps.accounts.models import OtpChallenge, RefreshSession, User
from apps.notifications.models import Notification
from tests import factories

from .helpers import PASSWORD, deliver_all, error_code, sms_code

pytestmark = pytest.mark.django_db

NEW = "another-long-passphrase"


def _token_in(message) -> str:
    return message.body.split("#token=", 1)[1].split()[0]


def _citizen(**kw):
    user = factories.citizen(**kw)
    user.set_password(PASSWORD)
    user.last_login = timezone.now()
    user.save()
    return user


# --- reset by SMS -----------------------------------------------------------------------------


def test_reset_by_sms_code_revokes_every_session(api, as_user):
    user = _citizen()
    old_session = as_user(user).tokens
    api.credentials()
    request = {"phone": user.phone}
    assert (
        api.post("/api/v1/auth/password/reset/request", request, format="json").status_code == 202
    )
    code = sms_code(api, user.phone)
    body = {"phone": user.phone, "code": code, "new_password": NEW}
    assert api.post("/api/v1/auth/password/reset/confirm", body, format="json").status_code == 204

    user.refresh_from_db()
    assert check_password(NEW, user.password)
    assert user.phone_verified_at is not None  # the code proved the phone
    assert not RefreshSession.objects.filter(user=user, revoked_at__isnull=True).exists()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {old_session.access}")
    assert api.get("/api/v1/me").status_code == 401
    assert Notification.objects.filter(recipient=user, template="password_changed").exists()


def test_reset_answers_the_same_for_unknown_and_dormant_numbers(api):
    dormant = _citizen()
    User.objects.filter(pk=dormant.pk).update(last_login=timezone.now() - timedelta(days=181))
    answers = [
        api.post("/api/v1/auth/password/reset/request", {"phone": p}, format="json")
        for p in ("01099999998", dormant.phone)
    ]
    assert answers[0].status_code == answers[1].status_code == 202
    assert answers[0].json() == answers[1].json()
    # A number unused for 180 days may belong to someone new: no code goes to it.
    assert not OtpChallenge.objects.exists()


def test_reset_with_a_wrong_code_changes_nothing(api):
    user = _citizen()
    api.post("/api/v1/auth/password/reset/request", {"phone": user.phone}, format="json")
    wrong = "000000" if sms_code(api, user.phone) != "000000" else "111111"
    body = {"phone": user.phone, "code": wrong, "new_password": NEW}
    response = api.post("/api/v1/auth/password/reset/confirm", body, format="json")
    assert response.status_code == 400
    assert error_code(response) == "INVALID_CODE"
    user.refresh_from_db()
    assert check_password(PASSWORD, user.password)


# --- change while logged in -------------------------------------------------------------------


def test_change_password_needs_the_current_one(as_user):
    user = _citizen()
    client = as_user(user)
    body = {"current_password": "wrong", "new_password": NEW}
    response = client.post("/api/v1/me/password", body, format="json")
    assert response.status_code == 400
    assert "current_password" in response.json()["error"]["fields"]


def test_change_password_logs_out_other_devices_and_keeps_this_one(api, as_user):
    user = _citizen()
    other_device = as_user(user).tokens
    client = as_user(user)
    body = {"current_password": PASSWORD, "new_password": NEW}
    response = client.post("/api/v1/me/password", body, format="json")
    assert response.status_code == 200
    fresh = response.json()

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh['access']}")
    assert api.get("/api/v1/me").status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {other_device.access}")
    assert api.get("/api/v1/me").status_code == 401


# --- profile and email ------------------------------------------------------------------------


def test_profile_update_cleans_text(as_user):
    client = as_user(_citizen())
    response = client.patch(
        "/api/v1/me", {"full_name": " রহিমা\u0000 খাতুন ", "preferred_language": "en"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "রহিমা খাতুন"
    assert response.json()["preferred_language"] == "en"


def test_email_is_verified_by_the_emailed_token(api, as_user):
    user = _citizen()
    client = as_user(user)
    assert (
        client.patch("/api/v1/me", {"email": "Rahima@Example.com"}, format="json").status_code
        == 200
    )
    deliver_all()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["rahima@example.com"]
    token = _token_in(mail.outbox[0])

    api.credentials()
    assert api.post("/api/v1/auth/email/verify", {"token": token}, format="json").status_code == 204
    user.refresh_from_db()
    assert user.email_verified_at is not None


def test_email_token_is_void_once_the_address_changes(api, as_user):
    user = _citizen()
    client = as_user(user)
    client.patch("/api/v1/me", {"email": "first@example.com"}, format="json")
    deliver_all()
    token = _token_in(mail.outbox[0])
    client.patch("/api/v1/me", {"email": "second@example.com"}, format="json")
    api.credentials()
    response = api.post("/api/v1/auth/email/verify", {"token": token}, format="json")
    assert error_code(response) == "INVALID_CODE"


def test_the_emailed_link_opens_the_public_site(as_user, settings):
    settings.PUBLIC_BASE_URL = "https://grs.example.org"
    as_user(_citizen()).patch("/api/v1/me", {"email": "rahima@example.com"}, format="json")
    deliver_all()
    assert "https://grs.example.org/verify-email#token=" in mail.outbox[0].body


def test_the_verification_email_has_a_button_and_no_bare_token(as_user):
    as_user(_citizen(preferred_language="en")).patch(
        "/api/v1/me", {"email": "rahima@example.com"}, format="json"
    )
    deliver_all()
    message = mail.outbox[0]
    token = _token_in(message)
    assert message.body.count(token) == 1  # only inside the link
    [(html, kind)] = message.alternatives
    assert kind == "text/html"
    assert f"/verify-email#token={token}" in html and ">Confirm email</a>" in html
    assert "ignore this email" in message.body and "ignore this email" in html


def test_an_account_gets_three_verification_emails_a_day(as_user):
    user = _citizen()
    client = as_user(user)
    for n in range(3):
        response = client.patch("/api/v1/me", {"email": f"try{n}@example.com"}, format="json")
        assert response.status_code == 200
    response = client.patch("/api/v1/me", {"email": "try3@example.com"}, format="json")
    assert error_code(response) == "RATE_LIMITED"
    assert int(response["Retry-After"]) > 23 * 3600
    user.refresh_from_db()
    assert user.email == "try2@example.com"  # the refused address was not taken either
    # Clearing the address sends nothing, so it is never refused.
    assert client.patch("/api/v1/me", {"email": ""}, format="json").status_code == 200


def test_verification_emails_stop_for_everyone_at_the_daily_cap(as_user, settings):
    settings.EMAIL_VERIFY_DAILY_CAP = 2
    for n in range(2):
        as_user(_citizen()).patch("/api/v1/me", {"email": f"u{n}@example.com"}, format="json")
    response = as_user(_citizen()).patch("/api/v1/me", {"email": "u2@example.com"}, format="json")
    assert error_code(response) == "RATE_LIMITED"
    assert Notification.objects.filter(template="verify_email").count() == 2


def test_verification_emails_older_than_a_day_do_not_count(as_user):
    user = _citizen()
    client = as_user(user)
    for n in range(3):
        client.patch("/api/v1/me", {"email": f"old{n}@example.com"}, format="json")
    # Notification is partitioned on created_at, so move the rows by re-dating them in SQL.
    Notification.objects.filter(recipient=user).update(
        created_at=timezone.now() - timedelta(days=1, minutes=1)
    )
    response = client.patch("/api/v1/me", {"email": "new@example.com"}, format="json")
    assert response.status_code == 200


def test_email_used_by_another_account_is_refused(as_user):
    factories.citizen(email="taken@example.com")
    client = as_user(_citizen())
    response = client.patch("/api/v1/me", {"email": "TAKEN@example.com"}, format="json")
    assert response.status_code == 409


def test_demo_inbox_is_closed_outside_demo_mode(api, settings):
    settings.DEMO_MODE = False
    assert api.get("/api/v1/demo/sms/01000000001").status_code == 404
