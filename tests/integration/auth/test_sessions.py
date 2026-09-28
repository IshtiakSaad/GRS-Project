from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import sessions
from apps.accounts.models import RefreshSession
from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from tests import factories

from .helpers import error_code

pytestmark = pytest.mark.django_db

REFRESH = "/api/v1/auth/token/refresh"


def _refresh(api, raw):
    api.credentials()
    return api.post(REFRESH, {"refresh": raw}, format="json")


def _bearer(api, access):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api


def test_refresh_rotates_the_token(api, as_user):
    user = factories.citizen()
    first = as_user(user).tokens
    response = _refresh(api, first.refresh)
    assert response.status_code == 200
    body = response.json()
    assert body["refresh"] != first.refresh
    assert body["session_id"] == str(first.session_id)
    assert _bearer(api, body["access"]).get("/api/v1/me").status_code == 200
    assert RefreshSession.objects.filter(rotated_at__isnull=False).count() == 1


def test_a_retry_within_the_grace_window_gets_the_same_successor(api, as_user):
    first = as_user(factories.citizen()).tokens
    a = _refresh(api, first.refresh).json()
    b = _refresh(api, first.refresh).json()  # the response to the first call was lost
    assert a["refresh"] == b["refresh"]
    assert RefreshSession.objects.filter(revoked_at__isnull=False).count() == 0


def test_reuse_after_the_grace_window_revokes_the_whole_family(api, as_user):
    user = factories.citizen()
    first = as_user(user).tokens
    second = _refresh(api, first.refresh).json()
    RefreshSession.objects.filter(rotated_at__isnull=False).update(
        rotated_at=timezone.now() - timedelta(minutes=5)
    )

    stolen = _refresh(api, first.refresh)
    assert stolen.status_code == 401
    assert error_code(stolen) == "SESSION_EXPIRED"
    # The legitimate holder is logged out too: nobody can tell which copy is the thief's.
    assert _refresh(api, second["refresh"]).status_code == 401
    assert _bearer(api, second["access"]).get("/api/v1/me").status_code == 401
    assert RefreshSession.objects.filter(revoke_reason="reuse").count() == 2
    assert AuditLog.objects.filter(action="auth.refresh_reuse").exists()
    assert Notification.objects.filter(recipient=user, template="session_reuse").exists()


def test_expired_session_cannot_refresh(api, as_user):
    first = as_user(factories.citizen()).tokens
    RefreshSession.objects.update(idle_expires_at=timezone.now() - timedelta(seconds=1))
    assert _refresh(api, first.refresh).status_code == 401


def test_idle_expiry_never_passes_the_absolute_limit(as_user):
    first = as_user(factories.citizen()).tokens
    soon = timezone.now() + timedelta(minutes=5)
    RefreshSession.objects.update(idle_expires_at=soon, absolute_expires_at=soon)
    sessions.rotate(first.refresh)
    child = RefreshSession.objects.get(rotated_at__isnull=True)
    assert child.idle_expires_at <= child.absolute_expires_at


@pytest.mark.parametrize("raw", ["", "short", "x" * 200, "a-random-but-unknown-token-value"])
def test_garbage_refresh_tokens_are_refused(api, raw):
    assert _refresh(api, raw).status_code in (400, 401)


def test_logout_ends_the_session_and_its_access_token_at_once(api, as_user):
    client = as_user(factories.citizen())
    tokens = client.tokens
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401  # no 10-minute tail
    assert _refresh(api, tokens.refresh).status_code == 401


def test_deactivation_and_role_changes_apply_to_live_tokens(as_user):
    user = factories.citizen()
    client = as_user(user)
    assert client.get("/api/v1/me").status_code == 200
    user.token_version += 1
    user.save()
    assert client.get("/api/v1/me").status_code == 401


def test_user_lists_and_ends_their_own_sessions(api, as_user):
    user = factories.citizen()
    phone_session = sessions.start(user, device_id=None, trust_mode="PERSONAL", mfa=False)
    client = as_user(user)
    listed = client.get("/api/v1/me/sessions").json()
    assert len(listed) == 2
    assert [s["current"] for s in listed].count(True) == 1

    other = client.delete(f"/api/v1/me/sessions/{phone_session.session_id}")
    assert other.status_code == 204
    assert _refresh(api, phone_session.refresh).status_code == 401


def test_a_user_cannot_end_someone_elses_session(as_user):
    victim_session = sessions.start(
        factories.citizen(), device_id=None, trust_mode="SHARED", mfa=False
    )
    client = as_user(factories.citizen())
    assert client.delete(f"/api/v1/me/sessions/{victim_session.session_id}").status_code == 404
    assert not RefreshSession.objects.filter(revoked_at__isnull=False).exists()


def test_malformed_bearer_headers_are_refused(api):
    for header in ("Bearer", "Bearer a b", "Bearer not-a-jwt", "Bearer é"):
        api.credentials(HTTP_AUTHORIZATION=header)
        assert api.get("/api/v1/me").status_code == 401
