"""Tests run against real PostgreSQL: constraints, triggers and row locks are behaviour."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-secret")
# Tests migrate and run as grs_owner, exactly like production migrations; role-specific tests
# connect separately as grs_api and grs_worker.
os.environ.setdefault("DATABASE_URL", "postgres://grs_owner:owner-local@localhost:5432/grs")
os.environ.setdefault("GRS_API_PASSWORD", "api-local")
os.environ.setdefault("GRS_WORKER_PASSWORD", "worker-local")
os.environ.setdefault("REDIS_CACHE_URL", "redis://localhost:6380/0")
os.environ.setdefault("REDIS_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "JWT_SIGNING_KEYS",
    "t1=test-only-jwt-signing-key-not-a-secret,t0=test-only-old-key-still-accepted-for-now",
)
os.environ.setdefault("JWT_ACTIVE_KID", "t1")
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", "dGVzdC1vbmx5LWZpZWxkLWtleS1ub3QtYS1zZWNyZXQ=")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:8333")
os.environ.setdefault("S3_PUBLIC_ENDPOINT", os.environ["S3_ENDPOINT"])

from .base import *  # noqa: E402

ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only; never in prod
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = False
LOGGING["root"]["level"] = "WARNING"
REVIEW_SAMPLE_RATE = 0.0  # deterministic; tests that need a sample set it
