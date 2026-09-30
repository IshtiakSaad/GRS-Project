"""One-time codes sent by SMS.

Codes are stored as HMAC-SHA256 with a server key, not with the password hasher: a 6-digit code
has too little entropy for slow hashing to matter, and putting it on the hasher would add CPU
load at the 9am peak. Guessing is bounded instead: 5 attempts per code, 10 minutes, and at most
3 codes per hour per phone.
"""

import hmac
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models.functions import Now
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.common.text import ascii_digits
from apps.notifications import services as notifications

from .models import OtpChallenge, User

LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5
COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 3
_CODE = re.compile(r"^[0-9]{6}$")


def _digest(phone: str, purpose: str, code: str) -> str:
    return salted_hmac("grs.otp", f"{phone}:{purpose}:{code}", algorithm="sha256").hexdigest()


def clean_code(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    code = ascii_digits(raw).strip()
    return code if _CODE.match(code) else None


def issue(user: User, purpose: str) -> bool:
    """Create a code and queue its SMS. False when the phone's sending limit is reached."""
    with transaction.atomic():
        # Serialises issuance per account, so two quick taps cannot both pass the limit.
        User.objects.select_for_update().filter(pk=user.pk).first()
        recent = OtpChallenge.objects.filter(
            phone=user.phone, purpose=purpose, created_at__gt=Now() - timedelta(hours=1)
        ).order_by("-created_at")
        latest = recent.values_list("created_at", flat=True).first()
        if latest is not None and latest > timezone.now() - COOLDOWN:
            return False
        if recent.count() >= MAX_PER_HOUR:
            return False

        code = f"{secrets.randbelow(10**6):06d}"
        OtpChallenge.objects.create(
            phone=user.phone,
            purpose=purpose,
            code_hmac=_digest(user.phone, purpose, code),
            expires_at=timezone.now() + LIFETIME,
        )
        notifications.queue(user, "otp", {"code": code}, expires_in=LIFETIME)
    return True


def verify(phone: str, purpose: str, raw_code) -> bool:
    """Check the newest live code for this phone; a wrong guess uses up one attempt."""
    code = clean_code(raw_code)
    with transaction.atomic():
        challenge = (
            OtpChallenge.objects.select_for_update()
            .filter(phone=phone, purpose=purpose, consumed_at__isnull=True, expires_at__gt=Now())
            .order_by("-created_at")
            .first()
        )
        if challenge is None or challenge.attempts >= MAX_ATTEMPTS:
            return False
        expected = _digest(phone, purpose, code or "")
        if code is not None and hmac.compare_digest(challenge.code_hmac, expected):
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
            return True
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        return False
