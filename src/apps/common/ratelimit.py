"""Application rate limits: a sliding-window counter in redis-cache.

The edge (Nginx) limits per IP, generously, because many citizens share one IP behind carrier
NAT. Here the key is the user, or the phone number on the unauthenticated auth routes.

Sliding-window counter: the count is this window's hits plus the previous window's hits
weighted by how much of it still overlaps the sliding window. Two small keys per limiter
instead of one entry per request. The Lua script runs atomically in Redis, using Redis's own
clock, so concurrent requests and skewed app hosts cannot overshoot.

If Redis is down the limit is skipped (fail open), and the durable login throttle in PostgreSQL
still applies. A dead cache must not take the service down with it.
"""

import hashlib
import logging
import math
import time
from dataclasses import dataclass
from functools import cache

import redis
from django.conf import settings
from django.utils.translation import gettext as _
from rest_framework.throttling import BaseThrottle

from .phone import normalise_phone

logger = logging.getLogger(__name__)

_SCRIPT = """
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local slot = math.floor(now / window)
local elapsed = now - slot * window
local current_key = KEYS[1] .. ':' .. slot
local previous = tonumber(redis.call('GET', KEYS[1] .. ':' .. (slot - 1)) or '0')
local current = tonumber(redis.call('GET', current_key) or '0')
if previous * (window - elapsed) / window + current + 1 > limit then
  return window - elapsed
end
redis.call('INCR', current_key)
-- Kept until the end of the next window, where it is the "previous" count.
redis.call('PEXPIREAT', current_key, (slot + 2) * window)
return 0
"""


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window: int  # seconds
    by: str = "user"  # "user", or "phone" for routes called before login


@cache
def _client() -> redis.Redis:
    return redis.Redis.from_url(
        settings.REDIS_CACHE_URL,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
    )


@cache
def _script():
    return _client().register_script(_SCRIPT)


_last_warning = 0.0


def _warn_open(exc: Exception) -> None:
    global _last_warning
    if time.monotonic() - _last_warning > 60:  # one line a minute, not one per request
        _last_warning = time.monotonic()
        logger.warning("rate limits off: redis-cache unavailable (%s)", exc)


def hit(rule: Rule, subject: str) -> int:
    """Count one hit. Returns 0 if allowed, else the seconds to wait."""
    digest = hashlib.sha256(subject.encode()).hexdigest()[:32]  # no phone numbers in Redis
    try:
        wait_ms = _script()(
            keys=[f"rl:{rule.name}:{digest}"], args=[rule.window * 1000, rule.limit]
        )
    except redis.RedisError as exc:
        _warn_open(exc)
        return 0
    return math.ceil(int(wait_ms) / 1000)


def _subject(rule: Rule, request) -> str | None:
    if rule.by == "phone":
        raw = request.data.get("phone") if hasattr(request.data, "get") else None
        return normalise_phone(raw) if isinstance(raw, str) else None
    user = request.user
    return str(user.pk) if user and user.is_authenticated else None


class RateLimit(BaseThrottle):
    """Applied to every view. A view opts in by naming its rules:

    - `rate_limits = {"POST": Rule(...)}`, per method, or
    - `def rate_limit(self, request) -> Rule | None`, when the rule depends on the request.
    """

    def allow_request(self, request, view):
        chooser = getattr(view, "rate_limit", None)
        rule = chooser(request) if callable(chooser) else None
        if rule is None:
            rule = getattr(view, "rate_limits", {}).get(request.method)
        if rule is None:
            return True
        subject = _subject(rule, request)
        if subject is None:  # no phone given: the input check will refuse it anyway
            return True
        wait = hit(rule, subject)
        if wait:
            # Imported here: DRF loads this class while apps.common.errors is importing DRF.
            from .errors import AppError

            raise AppError(
                "RATE_LIMITED",
                _("Too many requests. Try again in %(seconds)s seconds.") % {"seconds": wait},
                429,
                wait=wait,
            )
        return True


# The limits. Tuned by the load test; generous enough for a real person.
LOGIN = Rule("login", 20, 600, by="phone")
REGISTER = Rule("register", 5, 3600, by="phone")
CODE_CHECK = Rule("code-check", 10, 600, by="phone")
CODE_SEND = Rule("code-send", 5, 3600, by="phone")
SUBMIT = Rule("submit", 10, 3600)
COMMENT = Rule("comment", 30, 3600)
UPLOAD = Rule("upload", 30, 3600)
ADMIN_WRITE = Rule("admin-write", 30, 60)
