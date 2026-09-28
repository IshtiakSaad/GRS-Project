"""The correlation id for the current request or task, shared by logs, errors and Celery."""

import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Accept a caller's id only if it is short and plain, so it is safe to log and echo back.
_VALID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def new_request_id() -> str:
    return uuid.uuid4().hex


def accept_or_new(candidate: str | None) -> str:
    if candidate and _VALID.match(candidate):
        return candidate
    return new_request_id()


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)
