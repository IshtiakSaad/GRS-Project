"""Guards over every route: permissions are explicit, hashing stays on the bulkhead, messages
exist in Bangla."""

import re
from pathlib import Path

import pytest
from django.contrib.auth.hashers import make_password
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import translation
from rest_framework.views import APIView

from tests.conftest import _serving_path, bulkhead_routes

SRC = Path(__file__).parent.parent.parent / "src"


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p.callback


def _our_api_views():
    for route, callback in _walk(get_resolver().url_patterns):
        cls = getattr(callback, "cls", None)
        if cls and issubclass(cls, APIView) and cls.__module__.startswith("apps."):
            yield route, cls


def test_there_are_api_views_to_check():
    assert len(list(_our_api_views())) >= 15


def test_every_view_names_its_permissions():
    """Relying on the project default is not allowed: a reader must see who may call a view."""
    missing = [
        route
        for route, cls in _our_api_views()
        if not any("permission_classes" in vars(k) for k in cls.__mro__ if k is not APIView)
    ]
    assert missing == []


def test_public_views_are_the_ones_we_meant():
    from apps.accounts.permissions import IsPublic

    public = sorted(route for route, cls in _our_api_views() if IsPublic in cls.permission_classes)
    assert public == sorted(
        [
            "api/v1/auth/register",
            "api/v1/auth/otp/verify",
            "api/v1/auth/otp/resend",
            "api/v1/auth/login",
            "api/v1/auth/2fa/verify",
            "api/v1/auth/2fa/recovery",
            "api/v1/auth/token/refresh",
            "api/v1/auth/password/reset/request",
            "api/v1/auth/password/reset/confirm",
            "api/v1/auth/email/verify",
            "api/v1/demo/sms/<str:phone>",
            "api/v1/categories",
        ]
    )


def test_bulkhead_guard_catches_hashing_on_the_main_pool():
    token = _serving_path.set("/api/v1/me")
    try:
        with pytest.raises(pytest.fail.Exception, match="not route to api-auth"):
            make_password("anything")
    finally:
        _serving_path.reset(token)


def test_bulkhead_routes_include_every_password_route():
    routes = bulkhead_routes()
    for path in ("/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/me/password"):
        assert routes.match(path)
    assert not routes.match("/api/v1/me")
    assert not routes.match("/api/v1/auth/login/extra")


def _messages_in_code() -> list[str]:
    found = []
    call = re.compile(r"\b_\(\s*((?:\"[^\"]*\"\s*)+)\)")
    for path in (SRC / "apps").rglob("*.py"):
        for match in call.finditer(path.read_text(encoding="utf-8")):
            found.append("".join(re.findall(r"\"([^\"]*)\"", match.group(1))))
    return sorted(set(found))


def test_every_message_has_a_bangla_translation():
    messages = _messages_in_code()
    assert len(messages) >= 10
    with translation.override("bn"):
        untranslated = [m for m in messages if translation.gettext(m) == m]
    assert untranslated == [], "add these to src/locale/bn/LC_MESSAGES/django.po"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "expected"),
    [("bn", "ফোন নম্বর বা পাসওয়ার্ড সঠিক নয়।"), ("en", "Phone number or password is incorrect.")],
)
def test_errors_speak_the_callers_language(api, language, expected):
    response = api.post(
        "/api/v1/auth/login",
        {"phone": "01000000001", "password": "whatever-it-is"},
        format="json",
        HTTP_ACCEPT_LANGUAGE=language,
    )
    assert response.json()["error"]["message"] == expected


@pytest.mark.django_db
def test_english_is_the_default_for_api_callers(api):
    """A caller that names no language gets English; the web app always names one."""
    response = api.post(
        "/api/v1/auth/login", {"phone": "01000000001", "password": "whatever-it-is"}, format="json"
    )
    assert response.json()["error"]["message"] == "Phone number or password is incorrect."
