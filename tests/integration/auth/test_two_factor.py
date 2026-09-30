import pytest
from django.core.management import call_command

from apps.accounts import totp
from apps.accounts.models import RecoveryCode, RefreshSession, Role, User
from tests import factories

from .helpers import PASSWORD, current_totp, error_code

pytestmark = pytest.mark.django_db


def _enrolled_officer(as_user):
    officer = factories.officer()
    officer.set_password(PASSWORD)
    officer.save()
    client = as_user(officer)
    setup = client.post("/api/v1/auth/2fa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    body = {"current_password": PASSWORD, "code": current_totp(officer)}
    confirm = client.post("/api/v1/auth/2fa/confirm", body, format="json")
    assert confirm.status_code == 200
    return officer, confirm.json()


def test_a_stolen_access_token_cannot_enrol_two_step_login(as_user):
    """Enrolment issues a fresh session; without the password a 10-minute token would become
    a 12-hour one."""
    officer = factories.officer()
    client = as_user(officer)
    client.post("/api/v1/auth/2fa/setup")
    body = {"current_password": "guessed-wrong", "code": current_totp(officer)}
    response = client.post("/api/v1/auth/2fa/confirm", body, format="json")
    assert response.status_code == 400
    assert error_code(response) == "INVALID_CREDENTIALS"
    assert User.objects.get(pk=officer.pk).totp_enabled_at is None


def test_recovery_codes_survive_a_secret_key_rotation(api, as_user, settings):
    officer, body = _enrolled_officer(as_user)
    settings.SECRET_KEY = "rotated-" + "x" * 50
    settings.SECRET_KEY_FALLBACKS = []
    api.credentials()
    mfa_token = _password_step(api, officer)
    response = api.post(
        "/api/v1/auth/2fa/recovery",
        {"mfa_token": mfa_token, "code": body["recovery_codes"][3]},
        format="json",
    )
    assert response.status_code == 200


def _password_step(api, user):
    body = {"phone": user.phone, "password": PASSWORD}
    response = api.post("/api/v1/auth/login", body, format="json").json()
    assert response["mfa_required"] is True
    assert "access" not in response  # the password alone opens nothing
    return response["mfa_token"]


def test_enrolment_returns_recovery_codes_and_ends_other_sessions(as_user):
    officer, body = _enrolled_officer(as_user)
    assert len(body["recovery_codes"]) == 10
    assert RecoveryCode.objects.filter(user=officer).count() == 10
    officer.refresh_from_db()
    assert totp.decrypt_secret(officer.totp_secret_encrypted)  # stored encrypted, readable
    assert RefreshSession.objects.filter(user=officer, revoke_reason="totp_enabled").exists()
    assert RefreshSession.objects.get(user=officer, revoked_at__isnull=True).mfa is True


def test_login_needs_the_second_step(api, as_user):
    officer, _ = _enrolled_officer(as_user)
    api.credentials()
    mfa_token = _password_step(api, officer)
    # Enrolment used this time step's code; forget it so the test need not wait 30 s.
    User.objects.filter(pk=officer.pk).update(totp_last_counter=None)
    body = {"mfa_token": mfa_token, "code": current_totp(officer)}
    response = api.post("/api/v1/auth/2fa/verify", body, format="json")
    assert response.status_code == 200
    assert response.json()["access"]


def test_a_code_works_once(api, as_user):
    officer, _ = _enrolled_officer(as_user)
    User.objects.filter(pk=officer.pk).update(totp_last_counter=None)
    api.credentials()
    code = current_totp(officer)
    first = {"mfa_token": _password_step(api, officer), "code": code}
    second = {"mfa_token": _password_step(api, officer), "code": code}
    assert api.post("/api/v1/auth/2fa/verify", first, format="json").status_code == 200
    replay = api.post("/api/v1/auth/2fa/verify", second, format="json")
    assert replay.status_code == 400
    assert error_code(replay) == "INVALID_CODE"


def test_wrong_codes_are_throttled(api, as_user):
    officer, _ = _enrolled_officer(as_user)
    api.credentials()
    mfa_token = _password_step(api, officer)
    for _ in range(5):
        api.post(
            "/api/v1/auth/2fa/verify", {"mfa_token": mfa_token, "code": "000000"}, format="json"
        )
    blocked = api.post(
        "/api/v1/auth/2fa/verify", {"mfa_token": mfa_token, "code": "000000"}, format="json"
    )
    assert blocked.status_code == 429


def test_recovery_code_works_once(api, as_user):
    officer, body = _enrolled_officer(as_user)
    code = body["recovery_codes"][0].lower().replace("-", " ")  # typed loosely
    api.credentials()
    ok = api.post(
        "/api/v1/auth/2fa/recovery",
        {"mfa_token": _password_step(api, officer), "code": code},
        format="json",
    )
    assert ok.status_code == 200
    again = api.post(
        "/api/v1/auth/2fa/recovery",
        {"mfa_token": _password_step(api, officer), "code": code},
        format="json",
    )
    assert again.status_code == 400


def test_mfa_token_dies_with_a_password_change(api, as_user):
    officer, _ = _enrolled_officer(as_user)
    api.credentials()
    mfa_token = _password_step(api, officer)
    User.objects.filter(pk=officer.pk).update(token_version=99)
    response = api.post(
        "/api/v1/auth/2fa/verify", {"mfa_token": mfa_token, "code": "123456"}, format="json"
    )
    assert error_code(response) == "MFA_TOKEN_INVALID"


def test_citizens_cannot_enrol(as_user):
    client = as_user(factories.citizen())
    assert client.post("/api/v1/auth/2fa/setup").status_code == 403


def test_second_enrolment_is_refused(as_user):
    officer, _ = _enrolled_officer(as_user)
    client = as_user(User.objects.get(pk=officer.pk))
    assert error_code(client.post("/api/v1/auth/2fa/setup")) == "TOTP_ALREADY_ENABLED"


def test_createadmin_enrols_two_step_login(monkeypatch, capsys):
    monkeypatch.setenv("GRS_ADMIN_PASSWORD", PASSWORD)
    call_command("createadmin", phone="01000000077", name="First Admin")
    admin = User.objects.get(phone="+8801000000077")
    assert admin.role == Role.ADMIN
    assert admin.totp_enabled_at is not None
    assert RecoveryCode.objects.filter(user=admin).count() == 10
    out = capsys.readouterr().out
    assert "otpauth://totp/" in out
    assert PASSWORD not in out


def test_admin_endpoints_need_a_two_step_session(as_user, rf):
    from apps.accounts.permissions import IsAdmin

    admin = factories.admin()
    request = rf.get("/")
    request.user = admin
    request.auth = {"mfa": False}
    assert not IsAdmin().has_permission(request, None)
    request.auth = {"mfa": True}
    assert IsAdmin().has_permission(request, None)


# --- the public demo's administrator ----------------------------------------------------------


def _demo_admin():
    from apps.accounts import services

    user, _, _ = services.create_admin("+8801000000001", "Demo Admin", PASSWORD)
    return user


def _second_step(api, user, code):
    body = {"mfa_token": _password_step(api, user), "code": code}
    return api.post("/api/v1/auth/2fa/verify", body, format="json")


def test_the_demo_administrator_takes_the_fixed_code(api, settings):
    """Reviewers reach the administrator's screens with the password, then 123456."""
    settings.DEMO_MODE = True
    admin = _demo_admin()
    for _ in range(2):  # every time, not once
        response = _second_step(api, admin, "123456")
        assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    assert api.get("/api/v1/admin/stats").status_code == 200
    assert RefreshSession.objects.filter(user=admin, mfa=True).count() == 2


def test_the_fixed_code_does_nothing_outside_demo_mode(api, settings):
    """Two locks: a live deployment refuses the demo administrator's 010 number outright, and
    even with the first step already passed, the code is refused once demo mode is off."""
    settings.DEMO_MODE = True
    admin = _demo_admin()
    mfa_token = _password_step(api, admin)

    settings.DEMO_MODE = False
    body = {"phone": admin.phone, "password": PASSWORD}
    assert error_code(api.post("/api/v1/auth/login", body, format="json")) == "VALIDATION_ERROR"
    body = {"mfa_token": mfa_token, "code": "123456"}
    response = api.post("/api/v1/auth/2fa/verify", body, format="json")
    assert error_code(response) == "INVALID_CODE"


def test_the_fixed_code_works_for_no_other_administrator(api, settings):
    settings.DEMO_MODE = True
    other = factories.admin(totp_secret_encrypted=totp.encrypt_secret(totp.new_secret()))
    other.set_password(PASSWORD)
    other.save()
    assert error_code(_second_step(api, other, "123456")) == "INVALID_CODE"
