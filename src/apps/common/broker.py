"""Fast-path enqueue from web requests, with a circuit breaker.

Everything a web request enqueues is also a row in PostgreSQL that a sweeper picks up, so the
broker only makes work start sooner. When it is down, each attempt still costs a connection
timeout, and a submission enqueues several tasks: measured in the chaos run, requests queued
behind that for up to 20 s. So after one failure this process stops trying for COOLDOWN
and leaves the work to the sweepers; the first attempt after the cooldown probes again.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

COOLDOWN = 30.0  # seconds; the notification sweeper runs every 30 s anyway

_lock = threading.Lock()
_open_until = 0.0


def enqueue(task, *args, **kwargs) -> bool:
    """True if handed to the broker; False if skipped or failed (a sweeper will do it)."""
    global _open_until
    if time.monotonic() < _open_until:
        return False
    try:
        task.apply_async(args, kwargs)
    except Exception:  # noqa: BLE001 - any broker failure
        with _lock:
            _open_until = time.monotonic() + COOLDOWN
        logger.warning(
            "broker unavailable; enqueueing paused for %ss, sweepers will catch up", int(COOLDOWN)
        )
        return False
    return True


def reset() -> None:
    """Close the breaker (tests)."""
    global _open_until
    _open_until = 0.0
