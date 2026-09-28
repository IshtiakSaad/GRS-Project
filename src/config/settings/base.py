"""Settings shared by every environment. Values that differ per host come from the environment."""

from pathlib import Path

import environ

SRC_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Git commit of the running image; /health/ready reports it so a deploy can verify what is live.
BUILD_SHA = env("BUILD_SHA", default="dev")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.common",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# --- Database -------------------------------------------------------------------------------
# PostgreSQL is the only source of truth. The statement timeout sits at the bottom of the
# timeout ladder (statement < gunicorn < nginx) so a slow query fails before the worker is killed.
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 3,
    "options": (
        f"-c statement_timeout={env.int('DB_STATEMENT_TIMEOUT_MS', default=5000)}"
        f" -c idle_in_transaction_session_timeout="
        f"{env.int('DB_IDLE_IN_TX_TIMEOUT_MS', default=10000)}"
    ),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Redis ----------------------------------------------------------------------------------
# Two instances, split by failure behaviour: the broker must never evict a task, the cache may
# evict anything. Neither holds data we cannot lose; short timeouts keep a dead Redis from
# stalling a request.
REDIS_CACHE_URL = env("REDIS_CACHE_URL")
REDIS_BROKER_URL = env("REDIS_BROKER_URL")
REDIS_SOCKET_TIMEOUT = 0.5

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "TIMEOUT": 300,
        "OPTIONS": {
            "socket_connect_timeout": REDIS_SOCKET_TIMEOUT,
            "socket_timeout": REDIS_SOCKET_TIMEOUT,
        },
    }
}

# --- Celery ---------------------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_BROKER_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_timeout": 2, "socket_connect_timeout": 2}
# A publish that fails must fail fast: the outbox sweeper redelivers, so retrying inside a
# web request only adds latency.
CELERY_TASK_PUBLISH_RETRY = False
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 100
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE: dict = {}

# --- Internationalisation -------------------------------------------------------------------
# Timestamps are stored in UTC. Business dates (tracking-number year, working days, due dates)
# are computed in BUSINESS_TIME_ZONE.
LANGUAGE_CODE = "bn"
LANGUAGES = [("bn", "Bangla"), ("en", "English")]
TIME_ZONE = "UTC"
BUSINESS_TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = SRC_DIR.parent / "staticfiles"

# --- API ------------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.errors.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.KeysetPagination",
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Government Service Request API",
    "DESCRIPTION": (
        "Citizens file service requests, officers work them, administrators oversee them. "
        'Errors use one envelope: `{"error": {"code", "message", "fields", '
        '"request_id"}}`.'
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- Logging --------------------------------------------------------------------------------
# One JSON object per line on stdout, each carrying the request id.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.common.logging.RequestIdFilter"}},
    "formatters": {"json": {"()": "apps.common.logging.JsonFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["stdout"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.server": {"level": "WARNING"},
        "celery": {"level": "INFO"},
    },
}
