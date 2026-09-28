"""Health endpoints for Nginx, Compose and the deploy script.

Plain Django views: no auth, not part of the API schema.
"""

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def live(request):
    """The process is up. Checks nothing else, so a dependency outage never restarts it."""
    return JsonResponse({"status": "ok"})


def _redis_ok(url: str) -> bool:
    try:
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except redis.RedisError:
        return False


@require_GET
def ready(request):
    """Ready to take traffic. Only PostgreSQL is required; Redis being down is reported as degraded.

    Submissions depend on PostgreSQL alone: the outbox holds notifications until the broker is
    back, and rate limits fail open. So a Redis outage must not take the API out of rotation.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = True
    except Exception:  # noqa: BLE001 - any failure means not ready
        database = False

    degraded = [
        name
        for name, url in (
            ("redis-cache", settings.REDIS_CACHE_URL),
            ("redis-broker", settings.REDIS_BROKER_URL),
        )
        if not _redis_ok(url)
    ]

    body = {
        "status": "ok" if database else "unavailable",
        "build": settings.BUILD_SHA,
        "database": database,
        "degraded": degraded,
    }
    return JsonResponse(body, status=200 if database else 503)
