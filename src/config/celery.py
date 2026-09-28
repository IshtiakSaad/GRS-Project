import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("grs")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Carries X-Request-ID from the web request into every task it enqueues.
import apps.common.celery_signals  # noqa: E402, F401
