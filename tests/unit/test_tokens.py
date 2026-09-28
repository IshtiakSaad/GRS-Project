import time
import uuid
from types import SimpleNamespace

import jwt
import pytest

from apps.accounts import tokens

USER = SimpleNamespace(public_id=uuid.uuid4(), token_version=3)


def _access():
    return tokens.issue_access(USER, uuid.uuid4(), mfa=False)


def test_round_trip_carries_version_session_and_key_id():
    token = _access()
    assert jwt.get_unverified_header(token)["kid"] == "t1"
    claims = tokens.read_access(token)
    assert claims["sub"] == str(USER.public_id)
    assert claims["ver"] == 3
    assert claims["mfa"] is False


def test_tokens_signed_with_a_retiring_key_still_verify(settings):
    settings.JWT_ACTIVE_KID = "t0"
    token = _access()
    settings.JWT_ACTIVE_KID = "t1"
    assert tokens.read_access(token)["sub"] == str(USER.public_id)


def test_a_removed_key_invalidates_its_tokens(settings):
    token = _access()
    settings.JWT_SIGNING_KEYS = {"t2": "another-key-that-is-long-enough-to-use!!"}
    with pytest.raises(tokens.TokenError):
        tokens.read_access(token)


def test_alg_none_is_refused():
    claims = tokens.read_access(_access())
    forged = jwt.encode(claims, key=None, algorithm="none", headers={"kid": "t1"})
    with pytest.raises(tokens.TokenError):
        tokens.read_access(forged)


def test_tampered_payload_is_refused():
    head, body, sig = _access().split(".")
    _, other_body, _ = _access().split(".")
    with pytest.raises(tokens.TokenError):
        tokens.read_access(f"{head}.{other_body}.{sig}")


def test_expired_token_is_refused(settings):
    settings.ACCESS_TOKEN_SECONDS = -1
    token = _access()
    with pytest.raises(tokens.TokenError):
        tokens.read_access(token)


def test_a_two_factor_token_is_not_an_access_token():
    mfa = tokens.issue_mfa(USER, "device", "STAFF")
    with pytest.raises(tokens.TokenError):
        tokens.read_access(mfa)
    assert tokens.read_mfa(mfa)["trust"] == "STAFF"


def test_garbage_is_refused():
    for value in ("", "a.b.c", "x" * 3000):
        with pytest.raises(tokens.TokenError):
            tokens.read_access(value)


def test_issued_at_is_now():
    assert abs(tokens.read_access(_access())["iat"] - time.time()) < 5
