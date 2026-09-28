"""Tracking numbers: YY-NNNNNNN-C, e.g. 26-0004213-7.

YY is the submission year in Asia/Dhaka. NNNNNNN comes from that year's database sequence and
widens to eight digits instead of failing if a year ever exceeds ten million requests. C is a
Damm check digit: it catches every single wrong digit and every swap of two adjacent digits,
the usual mistakes when a number is read aloud over the phone.
"""

import re

from apps.common.text import ascii_digits

SERIAL_MIN_WIDTH = 7

# Damm's totally anti-symmetric quasigroup of order 10.
_DAMM = (
    (0, 3, 1, 7, 5, 9, 8, 6, 4, 2),
    (7, 0, 9, 2, 1, 5, 4, 8, 6, 3),
    (4, 2, 0, 6, 8, 7, 1, 3, 5, 9),
    (1, 7, 5, 0, 9, 8, 3, 4, 2, 6),
    (6, 1, 2, 3, 0, 4, 5, 9, 7, 8),
    (3, 6, 7, 4, 2, 0, 9, 5, 8, 1),
    (5, 8, 6, 9, 7, 2, 0, 1, 3, 4),
    (8, 9, 4, 5, 3, 6, 2, 0, 1, 7),
    (9, 4, 3, 8, 6, 1, 7, 2, 0, 5),
    (2, 5, 8, 1, 4, 3, 6, 7, 9, 0),
)

# Also enforced by a CHECK constraint on service_request.tracking_no.
TRACKING_RE = re.compile(r"^[0-9]{2}-[0-9]{7,8}-[0-9]$")
_ASCII_DIGITS = re.compile(r"^[0-9]{10,11}$")


def damm(digits: str) -> int:
    interim = 0
    for ch in digits:
        interim = _DAMM[interim][int(ch)]
    return interim


def format_tracking_no(year: int, serial: int) -> str:
    if serial < 1:
        raise ValueError("serial must be positive")
    yy = f"{year % 100:02d}"
    body = f"{serial:0{SERIAL_MIN_WIDTH}d}"
    return f"{yy}-{body}-{damm(yy + body)}"


def parse_tracking_no(raw: str) -> str | None:
    """Canonical form of user input, or None if it is malformed or fails the check digit.

    Accepts Bangla digits, spaces and missing dashes, so "২৬ ০০০৪২১৩ ৭" is found. Rejecting a
    typo here costs nothing; letting it reach the database costs a query.
    """
    digits = re.sub(r"[\s\-]", "", ascii_digits(raw or ""))
    if not _ASCII_DIGITS.match(digits):
        return None
    if damm(digits) != 0:
        return None
    return f"{digits[:2]}-{digits[2:-1]}-{digits[-1]}"
