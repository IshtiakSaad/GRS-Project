"""Settings shared by every environment. Values that differ per host come from the environment."""

from pathlib import Path

import environ

from config import api_docs

SRC_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
# Old keys stay here during a rotation so signed tokens issued before it keep working.
SECRET_KEY_FALLBACKS = env.list("DJANGO_SECRET_KEY_FALLBACKS", default=[])
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Git commit of the running image; /health/ready reports it so a deploy can verify what is live.
BUILD_SHA = env("BUILD_SHA", default="dev")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.common",
    "apps.accounts",
    "apps.directory",
    "apps.service_requests",
    "apps.sla",
    "apps.collab",
    "apps.admin_api",
    "apps.notifications",
    "apps.audit",
    "apps.monitoring",
]

AUTH_USER_MODEL = "accounts.User"

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
# PostgreSQL is the only source of truth. Each service connects as its own role, and the
# statement, lock and idle-in-transaction timeouts are set on those roles
# (deploy/postgres/roles.sql), so the database enforces them whatever the client does.
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["OPTIONS"] = {"connect_timeout": 3}
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
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_timeout": 2, "socket_connect_timeout": 1}
# A web request never waits long for a dead broker (the chaos run measured 4 s per attempt at
# Celery's default); apps.common.broker then stops trying for a while.
CELERY_BROKER_CONNECTION_TIMEOUT = 1
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
CELERY_BEAT_SCHEDULE: dict = {
    # Stored submit responses hold what citizens wrote; keep them only while a retry may
    # need them (24 h).
    "purge-idempotency-records": {
        "task": "apps.common.tasks.purge_idempotency_records",
        "schedule": 3600.0,
    },
    # Uploads whose verification task was lost (broker down, worker crash) are re-queued.
    "sweep-stuck-attachments": {
        "task": "apps.collab.tasks.sweep_stuck_attachments",
        "schedule": 300.0,
    },
    # Outbox safety net: messages the broker lost, dead workers' leases, stale status texts.
    "sweep-notifications": {
        "task": "apps.notifications.tasks.sweep",
        "schedule": 30.0,
    },
    # Requests past their deadline are flagged once per SLA cycle; staff are told.
    "escalate-overdue": {
        "task": "apps.sla.tasks.escalate_overdue",
        "schedule": 300.0,
    },
    # Hash-chain new audit rows and copy the anchors out of the database.
    "seal-audit-log": {
        "task": "apps.audit.tasks.seal_audit_log",
        "schedule": 60.0,
    },
}

# Share of resolutions sent to an administrator for review. Late rejections always are.
REVIEW_SAMPLE_RATE = env.float("REVIEW_SAMPLE_RATE", default=0.05)

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

LOCALE_PATHS = [SRC_DIR / "locale"]

# --- Identity -------------------------------------------------------------------------------
# Argon2id at the OWASP minimum (m=19 MiB, t=2, p=1). Measured 23 ms per hash on one core
# (tools/bench_password_hash.py); Django's default Argon2 costs 12x more for the same OWASP
# rating, which the 9am login burst cannot afford. Only one hasher: there are no legacy hashes.
PASSWORD_HASHERS = ["apps.accounts.hashers.Argon2idHasher"]
AUTH_PASSWORD_VALIDATORS = [
    # NIST 800-63B: a minimum length and a blocklist of common passwords, no composition rules.
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
PASSWORD_MAX_LENGTH = 128  # a longer input only costs hashing time

# Access tokens: HS256, signed with the key named by JWT_ACTIVE_KID. Older keys stay listed
# during a rotation so tokens already issued remain valid until they expire.
JWT_SIGNING_KEYS = env.dict("JWT_SIGNING_KEYS")  # kid=secret,kid=secret
JWT_ACTIVE_KID = env("JWT_ACTIVE_KID")
JWT_ISSUER = "grs"
ACCESS_TOKEN_SECONDS = 600

# TOTP secrets are encrypted at rest (Fernet). The first key encrypts; all keys decrypt.
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")

# Demo mode accepts only the unassigned +880 10 prefix, so no real person can be messaged,
# and exposes the fake SMS inbox. Never set on a system with real citizens.
DEMO_MODE = env.bool("DEMO_MODE", default=False)
SMS_BACKEND = env("SMS_BACKEND", default="fake")
# Demo mode only: the seeded demo administrator's second step accepts this fixed code, so
# reviewers can see the administrator's screens without an authenticator app. Nothing else
# accepts it, and outside demo mode it does not exist (apps/accounts/services.py).
DEMO_ADMIN_PHONE = "+8801000000001"
DEMO_ADMIN_TWO_STEP_CODE = "123456"
# Codes by SMS, for the whole site, per hour: the limit per phone does not stop someone asking
# for codes to thousands of numbers, each one paid for (apps/accounts/otp.py). Size it above
# the busiest real hour; when it is reached, codes pause for everyone until the hour rolls on.
SMS_CODES_HOURLY_CAP = env.int("SMS_CODES_HOURLY_CAP", default=300)

# Email leaves through SMTP. Locally that is Mailpit, which delivers nothing and shows every
# message at :8025; production relays through a provider (Resend on the demo) that delivers to
# real inboxes. The provider's key is EMAIL_HOST_PASSWORD, set only in the server's .env.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)  # implicit TLS, port 465
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@grs.example.com")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8080")
# A verification email goes to whatever address someone types, so it is the one message a
# stranger can aim at a third party. Capped per account, and for the whole site below the
# provider's daily quota, so a flood cannot use up the quota the real users need.
EMAIL_VERIFY_PER_ACCOUNT = 3  # a day
EMAIL_VERIFY_DAILY_CAP = env.int("EMAIL_VERIFY_DAILY_CAP", default=60)

# --- Attachments -------------------------------------------------------------------------------
# Files never pass through the app servers: clients upload to and download from the object
# store with short-lived presigned URLs. The store is self-hosted, in-country (decision 12).
# The API reaches it at S3_ENDPOINT; URLs handed to clients use S3_PUBLIC_ENDPOINT.
S3_ENDPOINT = env("S3_ENDPOINT", default="http://storage:8333")
S3_PUBLIC_ENDPOINT = env("S3_PUBLIC_ENDPOINT", default="http://localhost:8333")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default="grs-local")
S3_SECRET_KEY = env("S3_SECRET_KEY", default="grs-local-secret")
S3_BUCKET = env("S3_BUCKET", default="attachments")
S3_REGION = env("S3_REGION", default="us-east-1")

# --- Off-host store (audit anchors; PostgreSQL's WAL archive and base backups) ----------------
# A versioned, Object Lock bucket on another system. Production: AWS S3 with an empty endpoint
# and empty keys, so credentials come from the server's instance role. Locally: a bucket on the
# SeaweedFS container. See apps/audit/offsite.py.
OFFSITE_S3_BUCKET = env("OFFSITE_S3_BUCKET", default="offsite")
OFFSITE_S3_ENDPOINT = env("OFFSITE_S3_ENDPOINT", default=S3_ENDPOINT)
OFFSITE_S3_REGION = env("OFFSITE_S3_REGION", default="us-east-1")
OFFSITE_S3_ACCESS_KEY = env("OFFSITE_S3_ACCESS_KEY", default=S3_ACCESS_KEY)
OFFSITE_S3_SECRET_KEY = env("OFFSITE_S3_SECRET_KEY", default=S3_SECRET_KEY)
# How long each audit anchor is locked. GOVERNANCE: only an account holder with a separate
# bypass permission can remove it early; COMPLIANCE: nobody can, which a real deployment should
# use, for years. The demo uses GOVERNANCE for days so the account can be closed afterwards.
OFFSITE_LOCK_MODE = env("OFFSITE_LOCK_MODE", default="GOVERNANCE")
OFFSITE_LOCK_DAYS = env.int("OFFSITE_LOCK_DAYS", default=1)
# Swappable: the fake flags the EICAR test file; production uses ClamAV (clamd over TCP).
ATTACHMENT_SCANNER = env("ATTACHMENT_SCANNER", default="apps.collab.scanning.EicarScanner")
CLAMD_HOST = env("CLAMD_HOST", default="clamav")
CLAMD_PORT = env.int("CLAMD_PORT", default=3310)
CLAMD_TIMEOUT = env.float("CLAMD_TIMEOUT", default=30.0)

# --- Monitoring --------------------------------------------------------------------------------
# The monitor service reads Nginx's JSON access log, checks the site and its dependencies each
# minute, and pushes alerts to NTFY_URL (a private ntfy topic). Unset: alerts go to the log only.
NTFY_URL = env("NTFY_URL", default="")
MONITOR_SOURCE = env("MONITOR_SOURCE", default="local")
MONITOR_EDGE_LOG = env("MONITOR_EDGE_LOG", default="/var/log/grs/edge.json")
MONITOR_READY_URL = env("MONITOR_READY_URL", default="http://nginx/health/ready")
MONITOR_DISK_PATH = env("MONITOR_DISK_PATH", default="/var/log/grs")
MONITOR_TLS_HOST = env("MONITOR_TLS_HOST", default="")

# --- API ------------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.JWTAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.errors.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.KeysetPagination",
    # Every view passes through it; views name their own limits (apps/common/ratelimit.py).
    "DEFAULT_THROTTLE_CLASSES": ["apps.common.ratelimit.RateLimit"],
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Government Service Request API",
    "DESCRIPTION": api_docs.DESCRIPTION,
    "VERSION": "v1",  # the API's version, as in /api/v1/; releases are tagged in git
    "TAGS": api_docs.TAGS,
    "EXTENSIONS_ROOT": {"x-tagGroups": api_docs.TAG_GROUPS},
    # Keep the order the routes are declared in (register, verify, log in, …), not A to Z.
    "SORT_OPERATIONS": False,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "config.api_docs.add_summaries",
    ],
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Two choice sets share the field name `reason_code`; name each after what it means.
    "ENUM_NAME_OVERRIDES": {
        "PauseReasonEnum": "apps.service_requests.models.PauseReason",
        "RejectionReasonEnum": "apps.service_requests.models.RejectionReason",
        "RequestStatusEnum": "apps.service_requests.models.Status",
        "AttachmentStatusEnum": "apps.collab.models.AttachmentStatus",
        "BreakGlassReasonEnum": "apps.audit.models.BreakGlassReason",
    },
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
