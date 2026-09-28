"""The laptop profile: `docker compose up` with no cloud accounts and plain HTTP."""

from .base import *

# Off by default: with DEBUG on, Django answers 404s with an HTML page instead of the API's
# JSON error envelope, so local behaviour would differ from production.
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
