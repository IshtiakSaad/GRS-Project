from datetime import timedelta

import pytest

from apps.accounts import otp
from apps.accounts.models import OtpChallenge, RefreshSession, Role, User
from apps.audit.models import AuditLog
from apps.notifications.models import DemoSms, Notification
from apps.service_requests.models import Status
from tests import factories

from ..auth.helpers import deliver_all, error_code
from ..requests.helpers import cast, in_state

pytestmark = pytest.mark.django_db


def _new_officer(api, dept_code, phone="01099999777"):
    return api.post(
        "/api/v1/admin/users",
        {"phone": phone, "full_name": "Nasima Officer", "department": dept_code},
        format="json",
    )


def test_an_officer_is_created_without_a_password_and_sets_their_own(as_user, api):
    c = cast()
    admin_api = as_user(c.admin)
    response = _new_officer(admin_api, c.category.department.code)
    assert response.status_code == 201
    body = response.json()
    assert (body["role"], body["has_password"]) == (Role.OFFICER, False)
    officer = User.objects.get(public_id=body["id"])
    assert AuditLog.objects.filter(action="admin.user.create", target_id=officer.pk).exists()

    # The code went to the officer's own phone; only they can set the password.
    code = Notification.objects.get(recipient=officer, template="staff_welcome").payload["code"]
    api.credentials()
    confirmed = api.post(
        "/api/v1/auth/password/reset/confirm",
        {"phone": officer.phone, "code": code, "new_password": "a-long-new-passphrase-2026"},
        format="json",
    )
    assert confirmed.status_code == 204
    login = api.post(
        "/api/v1/auth/login",
        {"phone": officer.phone, "password": "a-long-new-passphrase-2026"},
        format="json",
    )
    assert login.status_code == 200


def test_one_account_per_phone(as_user):
    c = cast()
    api = as_user(c.admin)
    _new_officer(api, c.category.department.code)
    again = _new_officer(api, c.category.department.code)
    assert error_code(again) == "PHONE_IN_USE"


def test_deactivation_ends_access_at_once(as_user):
    c = cast()
    request = in_state(c, Status.ASSIGNED)
    officer_api = as_user(c.assigned)
    token = officer_api.tokens.access

    from rest_framework.test import APIClient

    admin_api = APIClient()
    admin_api.credentials(HTTP_AUTHORIZATION="Bearer " + _admin_token(c.admin))
    response = admin_api.patch(
        f"/api/v1/admin/users/{c.assigned.public_id}", {"is_active": False}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    officer_api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert officer_api.get(f"/api/v1/requests/{request.public_id}").status_code == 401
    assert not RefreshSession.objects.filter(user=c.assigned, revoked_at__isnull=True).exists()


def _admin_token(admin) -> str:
    from apps.accounts import sessions

    return sessions.start(admin, device_id=None, trust_mode="STAFF", mfa=True).access


def test_an_administrator_cannot_lock_themselves_out(as_user):
    c = cast()
    response = as_user(c.admin).patch(
        f"/api/v1/admin/users/{c.admin.public_id}", {"is_active": False}, format="json"
    )
    assert error_code(response) == "CANNOT_CHANGE_SELF"


def test_only_officers_have_a_department(as_user):
    c = cast()
    response = as_user(c.admin).patch(
        f"/api/v1/admin/users/{c.owner.public_id}",
        {"department": c.category.department.code},
        format="json",
    )
    assert "department" in response.json()["error"]["fields"]


def test_moving_an_officer_to_another_department(as_user):
    c = cast()
    other = factories.department()
    response = as_user(c.admin).patch(
        f"/api/v1/admin/users/{c.colleague.public_id}", {"department": other.code}, format="json"
    )
    assert response.json()["department"] == other.code


def test_a_staff_password_reset_ends_sessions_and_sends_a_code(as_user):
    c = cast()
    as_user(c.assigned)
    response = as_user(c.admin).post(f"/api/v1/admin/users/{c.assigned.public_id}/reset-password")
    assert response.status_code == 202
    c.assigned.refresh_from_db()
    assert not c.assigned.has_usable_password()
    assert not RefreshSession.objects.filter(user=c.assigned, revoked_at__isnull=True).exists()
    assert OtpChallenge.objects.filter(phone=c.assigned.phone, purpose="RESET_PASSWORD").exists()
    sms = Notification.objects.get(recipient=c.assigned, template="staff_reset")
    assert "/set-password/?phone=0" in sms.payload["link"]


def test_the_welcome_sms_says_what_happened_and_where_to_go(as_user, settings):
    """A new officer has never seen the site: the SMS names the role, links to the page that
    sets the password, and gives them a day to get to it."""
    settings.PUBLIC_BASE_URL = "https://grs.office.test"
    c = cast()
    _new_officer(as_user(c.admin), c.category.department.code, phone="01099999777")
    deliver_all()
    body = DemoSms.objects.get(phone="+8801099999777").body
    assert "https://grs.office.test/set-password/?phone=01099999777" in body
    assert "কর্মকর্তা" in body  # "officer", in the default language
    challenge = OtpChallenge.objects.get(phone="+8801099999777")
    lifetime = challenge.expires_at - challenge.created_at
    assert timedelta(hours=23) < lifetime <= otp.STAFF_SETUP_LIFETIME


def test_citizens_reset_their_own_passwords(as_user):
    c = cast()
    response = as_user(c.admin).post(f"/api/v1/admin/users/{c.owner.public_id}/reset-password")
    assert error_code(response) == "NOT_ALLOWED"


def test_listing_users(as_user):
    c = cast()
    api = as_user(c.admin)
    officers = api.get(
        f"/api/v1/admin/users?role=OFFICER&department={c.category.department.code}"
    ).json()["results"]
    assert {row["id"] for row in officers} == {
        str(c.assigned.public_id),
        str(c.colleague.public_id),
    }
    by_phone = api.get(f"/api/v1/admin/users?phone={c.owner.phone}").json()["results"]
    assert [row["id"] for row in by_phone] == [str(c.owner.public_id)]
    assert api.get("/api/v1/admin/users?role=KING").status_code == 400
