"""Time-based one-time passwords (RFC 6238), as used by authenticator apps.

Twenty lines of standard-library code instead of a dependency; the RFC's own test vectors
check it (tests/unit/test_totp.py). Secrets are stored encrypted (Fernet, rotatable keys).
"""

import base64
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

STEP = 30
DIGITS = 6
DRIFT_STEPS = 1  # accept the previous and next code: phone clocks drift


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()  # 160 bits, as RFC 4226 advises


def code_at(secret_b32: str, counter: int, digits: int = DIGITS, digest: str = "sha1") -> str:
    key = base64.b32decode(secret_b32)
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def matching_counter(secret_b32: str, code: str, after: int | None, now: float | None = None):
    """The time step the code belongs to, or None.

    Steps at or before `after` (the last one used) are refused, so a code seen over a
    shoulder or in a log cannot be replayed.
    """
    current = int((time.time() if now is None else now) // STEP)
    for counter in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if after is not None and counter <= after:
            continue
        if hmac.compare_digest(code_at(secret_b32, counter), code):
            return counter
    return None


def provisioning_uri(secret_b32: str, account: str, issuer: str = "GRS") -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret_b32}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"
    )


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in settings.FIELD_ENCRYPTION_KEYS])


def encrypt_secret(secret_b32: str) -> str:
    return _fernet().encrypt(secret_b32.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None
