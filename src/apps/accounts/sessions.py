"""Refresh sessions (design §7.2).

A refresh token is 256 random bits; only its SHA-256 is stored. Each use rotates it. The chain
of tokens from one login is a family; presenting a token that was already rotated means it was
copied, so the whole family is revoked.

Grace window: on a 3G link the response carrying the new token is often lost and the app
retries with the old one. The successor is derived from the old token (HMAC), so within 60
seconds the server can hand back the same successor instead of treating the retry as theft.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.audit import services as audit
from apps.notifications import services as notifications

from . import tokens
from .models import RefreshSession, Role, TrustMode, User

GRACE = timedelta(seconds=60)

# (idle, absolute). Shared devices (cyber cafés, Union Digital Centres) are the default for
# citizens; "this is my own phone" is an explicit choice. Staff sessions fit an office day.
LIFETIMES = {
    TrustMode.PERSONAL: (timedelta(days=30), timedelta(days=90)),
    TrustMode.SHARED: (timedelta(minutes=30), timedelta(hours=8)),
    TrustMode.STAFF: (timedelta(hours=4), timedelta(hours=12)),
}
ADMIN_LIFETIME = (timedelta(minutes=30), timedelta(hours=8))


class InvalidRefresh(Exception):
    pass


@dataclass
class Tokens:
    access: str
    refresh: str
    session_id: uuid.UUID
    expires_in: int

    def as_dict(self) -> dict:
        return {
            "access": self.access,
            "refresh": self.refresh,
            "session_id": str(self.session_id),
            "token_type": "Bearer",
            "expires_in": self.expires_in,
        }


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _successor(raw: str) -> str:
    return salted_hmac("grs.refresh.successor", raw, algorithm="sha256").hexdigest()


def trust_mode_for(user: User, requested: str | None) -> str:
    if user.role != Role.CITIZEN:
        return TrustMode.STAFF
    return TrustMode.PERSONAL if requested == TrustMode.PERSONAL else TrustMode.SHARED


def _lifetime(user: User, trust_mode: str) -> tuple[timedelta, timedelta]:
    return ADMIN_LIFETIME if user.role == Role.ADMIN else LIFETIMES[trust_mode]


def _tokens(user: User, session: RefreshSession, raw: str) -> Tokens:
    return Tokens(
        access=tokens.issue_access(user, session.family_id, session.mfa),
        refresh=raw,
        session_id=session.family_id,
        expires_in=settings.ACCESS_TOKEN_SECONDS,
    )


def start(
    user: User, *, device_id: str | None, trust_mode: str, mfa: bool, user_agent: str = ""
) -> Tokens:
    idle, absolute = _lifetime(user, trust_mode)
    now = timezone.now()
    raw = secrets.token_urlsafe(32)
    session = RefreshSession.objects.create(
        user=user,
        family_id=uuid.uuid4(),
        device_id=device_id,
        trust_mode=trust_mode,
        mfa=mfa,
        token_hash=_hash(raw),
        user_agent=user_agent[:255],
        last_used_at=now,
        idle_expires_at=now + idle,
        absolute_expires_at=now + absolute,
    )
    return _tokens(user, session, raw)


def rotate(raw: str, http_request=None) -> Tokens:
    if not isinstance(raw, str) or not 20 <= len(raw) <= 128:
        raise InvalidRefresh
    theft = False
    with transaction.atomic():
        session = (
            RefreshSession.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash(raw))
            .first()
        )
        if session is None or session.revoked_at is not None or not session.user.is_active:
            raise InvalidRefresh
        now = timezone.now()
        user = session.user
        successor = _successor(raw)

        if session.rotated_at is not None:
            child = RefreshSession.objects.filter(
                token_hash=_hash(successor), rotated_at__isnull=True, revoked_at__isnull=True
            ).first()
            if now - session.rotated_at <= GRACE and child is not None:
                return _tokens(user, child, successor)  # a retry, not a thief
            revoke_family(session.family_id, "reuse")
            audit.record(
                "auth.refresh_reuse",
                actor=user,
                target=user,
                data={"session": str(session.family_id)},
                http_request=http_request,
            )
            notifications.queue(user, "session_reuse", {})
            theft = True
        elif now >= session.idle_expires_at or now >= session.absolute_expires_at:
            raise InvalidRefresh
        else:
            idle, _ = _lifetime(user, session.trust_mode)
            child = RefreshSession.objects.create(
                user=user,
                family_id=session.family_id,
                parent=session,
                device_id=session.device_id,
                trust_mode=session.trust_mode,
                mfa=session.mfa,
                token_hash=_hash(successor),
                user_agent=session.user_agent,
                last_used_at=now,
                idle_expires_at=min(now + idle, session.absolute_expires_at),
                absolute_expires_at=session.absolute_expires_at,
            )
            session.rotated_at = now
            session.save(update_fields=["rotated_at"])
            return _tokens(user, child, successor)
    if theft:  # raised after the commit, so the revocation sticks
        raise InvalidRefresh


def revoke_family(family_id, reason: str) -> int:
    return RefreshSession.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason
    )


def revoke_all(user: User, reason: str) -> int:
    return RefreshSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason
    )


def active_sessions(user: User):
    """The newest token of each live family: one row per logged-in device."""
    now = timezone.now()
    return RefreshSession.objects.filter(
        user=user,
        revoked_at__isnull=True,
        rotated_at__isnull=True,
        idle_expires_at__gt=now,
        absolute_expires_at__gt=now,
    ).order_by("-last_used_at")
