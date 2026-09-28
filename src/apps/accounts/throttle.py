"""Progressive delay after failed logins, per account and device (design §7.3).

After 5 failures the next attempt must wait 1 minute, then 2, 4, 8, capped at 15. No hard
lockout: a delay slows guessing to a crawl, while a lockout would let anyone lock an officer
out by typing wrong passwords. Known devices have their own bucket, so an attacker on unknown
devices cannot delay the officer's own phone.

State lives in PostgreSQL: a Redis outage must not reset it. Phones with no account get the
same schedule from the cache, so the response sequence does not reveal which numbers exist.
"""

import hashlib
import logging
import math
import time

from django.core.cache import cache
from django.db import connection

from .models import LoginThrottle

logger = logging.getLogger(__name__)

FREE_FAILURES = 5
BASE_DELAY = 60
MAX_DELAY = 15 * 60
UNKNOWN_DEVICE = "unknown"


def delay_after(failures: int) -> int:
    if failures < FREE_FAILURES:
        return 0
    return min(BASE_DELAY * 2 ** (failures - FREE_FAILURES), MAX_DELAY)


def wait_seconds(user, device_key: str) -> int:
    row = (
        LoginThrottle.objects.filter(user=user, device_key=device_key)
        .values_list("next_allowed_at", flat=True)
        .first()
    )
    if row is None:
        return 0
    return max(0, math.ceil(row.timestamp() - time.time()))


def record_failure(user, device_key: str) -> None:
    # One atomic statement: concurrent failures each count, and no lock is held while hashing.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO login_throttle (user_id, device_key, failures, updated_at)
            VALUES (%(user)s, %(device)s, 1, now())
            ON CONFLICT (user_id, device_key) DO UPDATE SET
                failures = LEAST(login_throttle.failures + 1, 1000),
                updated_at = now(),
                next_allowed_at = CASE
                    WHEN login_throttle.failures + 1 >= %(free)s THEN now() + make_interval(
                        secs => LEAST(%(base)s * power(2, login_throttle.failures + 1 - %(free)s),
                                      %(max)s))
                END
            """,
            {
                "user": user.pk,
                "device": device_key,
                "free": FREE_FAILURES,
                "base": BASE_DELAY,
                "max": MAX_DELAY,
            },
        )


def clear(user, device_key: str) -> None:
    LoginThrottle.objects.filter(user=user, device_key=device_key).delete()


# --- phones without an account ----------------------------------------------------------------


def _phantom_key(phone: str) -> str:
    return "login-phantom:" + hashlib.sha256(phone.encode()).hexdigest()


def phantom_wait_seconds(phone: str) -> int:
    try:
        state = cache.get(_phantom_key(phone))
    except Exception:  # noqa: BLE001 - cache down: fail open
        return 0
    if not state:
        return 0
    return max(0, math.ceil(state["until"] - time.time()))


def phantom_record_failure(phone: str) -> None:
    key = _phantom_key(phone)
    try:
        state = cache.get(key) or {"failures": 0, "until": 0}
        state["failures"] += 1
        state["until"] = time.time() + delay_after(state["failures"])
        cache.set(key, state, timeout=MAX_DELAY + 3600)
    except Exception:  # noqa: BLE001 - cache down: fail open, but say so
        logger.warning("login throttle for unknown phones unavailable: cache down")
