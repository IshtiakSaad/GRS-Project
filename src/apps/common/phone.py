"""Bangladeshi mobile numbers, typed any common way, reduced to one form: +8801XXXXXXXXX."""

import re

from django.conf import settings

from .text import ascii_digits

_SEPARATORS = re.compile(r"[\s\-().]")
_LOCAL = re.compile(r"^01[0-9]{9}$")

# 013-019 are the operators' prefixes. 010 is unassigned: demo mode uses it so that no real
# person can ever receive a demo message.
_LIVE_PREFIX = re.compile(r"^\+8801[3-9][0-9]{8}$")
_DEMO_PREFIX = re.compile(r"^\+88010[0-9]{8}$")


def normalise_phone(raw: str) -> str | None:
    """Return the E.164 form, or None if this is not an accepted mobile number.

    Accepts Bangla digits, spaces and dashes, and the forms 01…, 8801…, +8801…, 008801….
    """
    if not isinstance(raw, str) or len(raw) > 32:
        return None
    value = _SEPARATORS.sub("", ascii_digits(raw))
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("880"):
        value = "+" + value
    elif _LOCAL.match(value):
        value = "+88" + value
    allowed = _DEMO_PREFIX if settings.DEMO_MODE else _LIVE_PREFIX
    return value if allowed.match(value) else None
