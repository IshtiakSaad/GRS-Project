import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import psycopg
import pytest
from django.db import connection


@contextmanager
def _connect_as(role: str, password_env: str):
    """A separate autocommit connection to the test database as a runtime role.

    It logs in as that role, so the role's own settings (timeouts) apply exactly as in
    production, which SET ROLE would not do.
    """
    s = connection.settings_dict
    conn = psycopg.connect(
        host=s["HOST"],
        port=s["PORT"] or 5432,
        dbname=s["NAME"],
        user=role,
        password=os.environ[password_env],
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def as_api(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), _connect_as("grs_api", "GRS_API_PASSWORD") as conn:
        yield conn


@pytest.fixture
def as_worker(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), _connect_as("grs_worker", "GRS_WORKER_PASSWORD") as conn:
        yield conn


@pytest.fixture
def connect_as(django_db_setup, django_db_blocker):
    """Factory for extra connections, e.g. to race two sessions against each other."""

    def factory(role="grs_api", password_env="GRS_API_PASSWORD"):
        return _connect_as(role, password_env)

    with django_db_blocker.unblock():
        yield factory


# --- API helpers ------------------------------------------------------------------------------


@pytest.fixture
def api():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def as_user(api):
    """as_user(user) -> an API client logged in as that user (a real session and token)."""
    from apps.accounts import sessions

    def login(user, mfa=None):
        issued = sessions.start(
            user,
            device_id=None,
            trust_mode=sessions.trust_mode_for(user, None),
            mfa=user.totp_enabled_at is not None if mfa is None else mfa,
        )
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access}")
        api.tokens = issued
        return api

    return login


@pytest.fixture(autouse=True)
def _empty_cache():
    """Tests share one Redis database; start each with an empty cache (throttles, markers)."""
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def _broker_breaker_closed():
    """An outage simulated by one test must not leave enqueueing paused for the next."""
    from apps.common import broker

    broker.reset()
    yield
    broker.reset()


# --- bulkhead guard ---------------------------------------------------------------------------
# Every password hash computed while serving a request must be on a route that Nginx sends to
# the api-auth bulkhead. The guard runs during every test; a new view that hashes
# on the main pool fails whichever test first calls it.

_serving_path: ContextVar[str | None] = ContextVar("serving_path", default=None)


def bulkhead_routes() -> re.Pattern:
    conf = (Path(__file__).parent.parent / "deploy/nginx/grs/api.conf").read_text()
    match = re.search(r"location ~ (\S+) \{\s*proxy_pass http://api_auth;", conf)
    assert match, "api-auth location not found in deploy/nginx/grs/api.conf"
    return re.compile(match.group(1))


def check_hash_is_on_bulkhead() -> None:
    path = _serving_path.get()
    if path is not None and not bulkhead_routes().match(path):
        pytest.fail(f"password hashed on {path}, which Nginx does not route to api-auth")


@pytest.fixture(autouse=True)
def _bulkhead_guard(monkeypatch):
    from django.contrib.auth.hashers import get_hasher
    from django.core.handlers.base import BaseHandler

    serve = BaseHandler.get_response

    def get_response(self, request):
        token = _serving_path.set(request.path)
        try:
            return serve(self, request)
        finally:
            _serving_path.reset(token)

    monkeypatch.setattr(BaseHandler, "get_response", get_response)
    hasher = type(get_hasher("default"))
    for name in ("encode", "verify"):
        original = getattr(hasher, name)

        def guarded(self, *args, _original=original, **kwargs):
            check_hash_is_on_bulkhead()
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(hasher, name, guarded)
