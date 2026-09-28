"""Public identifiers.

Internal keys are bigint identities: small indexes, cheap joins, never exposed. Public ids are
UUIDv7: time-ordered, so their unique index grows at the right edge instead of splitting random
pages like UUIDv4 does. The creation time they reveal is not secret.
"""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 version 7: 48-bit Unix milliseconds, then 74 random bits."""
    millis = time.time_ns() // 1_000_000
    raw = bytearray(millis.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(raw))
