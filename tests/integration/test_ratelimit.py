import pytest
import redis

from apps.accounts.views import LoginView
from apps.admin_api.views import AdminView
from apps.common import ratelimit
from apps.common.ratelimit import Rule
from apps.service_requests.models import Status
from tests import factories

from .auth.helpers import error_code
from .requests.helpers import act, cast, in_state

pytestmark = pytest.mark.django_db


def test_the_window_allows_the_limit_then_says_how_long_to_wait():
    rule = Rule("t-window", 3, 60)
    assert [ratelimit.hit(rule, "alice") for _ in range(3)] == [0, 0, 0]
    wait = ratelimit.hit(rule, "alice")
    assert 0 < wait <= 60
    assert ratelimit.hit(rule, "bob") == 0  # each subject has its own count


def test_a_refused_hit_is_not_counted():
    """Otherwise a client retrying while limited would never get back under the limit."""
    rule = Rule("t-refused", 1, 60)
    ratelimit.hit(rule, "carol")
    for _ in range(5):
        ratelimit.hit(rule, "carol")
    client = ratelimit._client()
    counts = [int(client.get(k)) for k in client.scan_iter("rl:t-refused:*")]
    assert counts == [1]


def _login(api, phone):
    return api.post("/api/v1/auth/login", {"phone": phone, "password": "wrong"}, format="json")


def test_login_is_limited_per_phone(api, monkeypatch):
    monkeypatch.setattr(LoginView, "rate_limits", {"POST": Rule("t-login", 2, 600, by="phone")})
    target = factories.citizen()
    assert [_login(api, target.phone).status_code for _ in range(2)] == [401, 401]
    limited = _login(api, target.phone)
    assert limited.status_code == 429
    assert error_code(limited) == "RATE_LIMITED"
    assert int(limited["Retry-After"]) > 0
    # The same phone typed differently is the same phone.
    local = "0" + target.phone.removeprefix("+880")
    assert _login(api, local).status_code == 429
    assert _login(api, factories.citizen().phone).status_code == 401  # another phone: fine


def test_submitting_is_limited_per_user(as_user, monkeypatch):
    monkeypatch.setattr(ratelimit, "SUBMIT", Rule("t-submit", 1, 3600))
    c = cast()
    api = as_user(c.owner)
    first = factories.draft(owner=c.owner, cat=c.category, title="One")
    second = factories.draft(owner=c.owner, cat=c.category, title="Two")
    assert act(api, first, "submit").status_code == 200
    assert error_code(act(api, second, "submit")) == "RATE_LIMITED"
    # Other actions are not the submit limit's business.
    request = in_state(c, Status.SUBMITTED)
    assert act(api, request, "withdraw").status_code == 200


def test_admin_changes_are_limited(as_user, monkeypatch):
    limit = Rule("t-admin", 1, 60)
    monkeypatch.setattr(AdminView, "rate_limits", {"POST": limit})
    c = cast()
    api = as_user(c.admin)
    body = {"code": "ONE", "name_bn": "এক", "name_en": "One"}
    assert api.post("/api/v1/admin/departments", body, format="json").status_code == 201
    again = api.post("/api/v1/admin/departments", {**body, "code": "TWO"}, format="json")
    assert again.status_code == 429
    assert api.get("/api/v1/admin/departments").status_code == 200  # reads are not limited


def test_limits_fail_open_when_the_cache_is_down(api, monkeypatch):
    def down():
        raise redis.ConnectionError("redis-cache down")

    monkeypatch.setattr(ratelimit, "_script", down)
    monkeypatch.setattr(LoginView, "rate_limits", {"POST": Rule("t-open", 1, 600, by="phone")})
    target = factories.citizen()
    # Nothing is counted, nothing is refused; the durable login throttle still applies.
    assert [_login(api, target.phone).status_code for _ in range(3)] == [401, 401, 401]


def test_every_route_open_before_login_has_a_limit():
    """A public endpoint that changes state is where abuse starts; each one names its limit,
    or is listed here with the reason it needs none."""
    from django.urls import get_resolver

    from apps.accounts.permissions import IsPublic

    no_limit_needed = {
        "api/v1/auth/2fa/verify": "the database throttle per account applies",
        "api/v1/auth/2fa/recovery": "the database throttle per account applies",
        "api/v1/auth/token/refresh": "256-bit random tokens cannot be guessed",
        "api/v1/auth/email/verify": "signed tokens cannot be guessed",
    }
    missing = []
    for route, cls in _routes(get_resolver()):
        if IsPublic in getattr(cls, "permission_classes", []) and hasattr(cls, "post"):
            limited = "POST" in getattr(cls, "rate_limits", {}) or hasattr(cls, "rate_limit")
            if not limited and route not in no_limit_needed:
                missing.append(route)
    assert missing == []


def _routes(resolver, prefix=""):
    from django.urls import URLPattern, URLResolver

    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            yield from _routes(entry, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern) and hasattr(entry.callback, "view_class"):
            yield prefix + str(entry.pattern), entry.callback.view_class
