"""Signed short-lived tokens: access tokens and the half-way token of a two-factor login.

HS256 only: the verifier names the one algorithm it accepts, so a token cannot choose its own
("alg": "none", or RS/HS confusion). Each token names its key (`kid`), so keys can be rotated
without logging everybody out.
"""

import time
import uuid

import jwt
from django.conf import settings

ALGORITHM = "HS256"
MFA_TOKEN_SECONDS = 300


class TokenError(Exception):
    pass


def _encode(claims: dict, lifetime: int) -> str:
    now = int(time.time())
    payload = {
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
        **claims,
    }
    kid = settings.JWT_ACTIVE_KID
    return jwt.encode(
        payload, settings.JWT_SIGNING_KEYS[kid], algorithm=ALGORITHM, headers={"kid": kid}
    )


def _decode(token: str, typ: str) -> dict:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = settings.JWT_SIGNING_KEYS.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise TokenError("unknown key")
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims["typ"] != typ:
        raise TokenError("wrong token type")
    return claims


def issue_access(user, family_id: uuid.UUID, mfa: bool) -> str:
    return _encode(
        {
            "typ": "access",
            "sub": str(user.public_id),
            "ver": user.token_version,
            "sid": str(family_id),
            "mfa": mfa,
        },
        settings.ACCESS_TOKEN_SECONDS,
    )


def read_access(token: str) -> dict:
    return _decode(token, "access")


def issue_mfa(user, device_id: str | None, trust_mode: str) -> str:
    """Proof that the password was right; exchanged for tokens with a valid second factor."""
    return _encode(
        {
            "typ": "mfa",
            "sub": str(user.public_id),
            "ver": user.token_version,
            "dev": device_id,
            "trust": trust_mode,
        },
        MFA_TOKEN_SECONDS,
    )


def read_mfa(token: str) -> dict:
    return _decode(token, "mfa")
