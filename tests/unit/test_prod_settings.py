"""Production settings refuse to start with values that would silently break email.

Each case imports config.settings.prod in a fresh interpreter, with an environment like a
server's .env, so nothing here depends on the test settings already loaded.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

SERVER_ENV = {
    "DJANGO_SECRET_KEY": "a-real-looking-secret-for-this-test-0123456789",
    "DATABASE_URL": "postgres://grs_api:x@postgres:5432/grs",
    "REDIS_CACHE_URL": "redis://redis-cache:6379/0",
    "REDIS_BROKER_URL": "redis://redis-broker:6379/0",
    "JWT_SIGNING_KEYS": "k1=a-real-looking-jwt-key-0123456789",
    "JWT_ACTIVE_KID": "k1",
    "FIELD_ENCRYPTION_KEYS": "cmVhbC1sb29raW5nLWZpZWxkLWtleS0wMTIzNDU2Nzg=",
    "S3_SECRET_KEY": "a-real-looking-storage-secret",
    "GRS_DOMAIN": "grs.office.test",
    "EMAIL_HOST": "smtp.resend.com",
}


def _load(**overrides):
    inherited = ("EMAIL_", "PUBLIC_", "DEFAULT_FROM_", "DJANGO_SETTINGS")
    env = {k: v for k, v in os.environ.items() if not k.startswith(inherited)}
    env |= SERVER_ENV | overrides
    code = "import config.settings.prod as s; print(s.PUBLIC_BASE_URL + '|' + s.DEFAULT_FROM_EMAIL)"
    return subprocess.run(  # noqa: S603 - a fixed command in our own interpreter
        [sys.executable, "-c", code],
        env={**env, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_links_and_sender_follow_the_domain():
    result = _load()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().split("|") == [
        "https://grs.office.test",
        "GRS <no-reply@grs.office.test>",
    ]


@pytest.mark.parametrize(
    ("overrides", "complaint"),
    [
        ({"PUBLIC_BASE_URL": "http://localhost:8080"}, "PUBLIC_BASE_URL"),
        ({"PUBLIC_BASE_URL": "http://grs.office.test"}, "PUBLIC_BASE_URL"),
        ({"EMAIL_HOST": "mailpit"}, "SMTP relay"),
        ({"DEFAULT_FROM_EMAIL": "no-reply@grs.example.com"}, "SMTP relay"),
        ({"EMAIL_HOST_USER": "resend", "EMAIL_HOST_PASSWORD": ""}, "SMTP relay"),
    ],
)
def test_refuses_email_that_would_not_reach_anyone(overrides, complaint):
    result = _load(**overrides)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr and complaint in result.stderr
