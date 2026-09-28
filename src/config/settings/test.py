"""Tests run against real PostgreSQL: constraints, triggers and row locks are behaviour."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-secret")
os.environ.setdefault("DATABASE_URL", "postgres://grs:grs@localhost:5432/grs")
os.environ.setdefault("REDIS_CACHE_URL", "redis://localhost:6380/0")
os.environ.setdefault("REDIS_BROKER_URL", "redis://localhost:6379/0")

from .base import *  # noqa: E402

ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only; never in prod
CELERY_TASK_ALWAYS_EAGER = False
LOGGING["root"]["level"] = "WARNING"
