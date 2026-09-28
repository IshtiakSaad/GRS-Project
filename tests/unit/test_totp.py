import base64

import pytest

from apps.accounts import totp

# RFC 6238 Appendix B: SHA-1, 8 digits, secret "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("unix_time", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_rfc_6238_vectors(unix_time, expected):
    assert totp.code_at(RFC_SECRET, unix_time // 30, digits=8) == expected


def test_accepts_one_step_of_clock_drift_either_way():
    secret = totp.new_secret()
    now = 1_800_000_000
    for step in (-1, 0, 1):
        code = totp.code_at(secret, now // 30 + step)
        assert totp.matching_counter(secret, code, None, now=now) == now // 30 + step
    old = totp.code_at(secret, now // 30 - 2)
    assert totp.matching_counter(secret, old, None, now=now) is None


def test_a_used_code_cannot_be_replayed():
    secret = totp.new_secret()
    now = 1_800_000_000
    code = totp.code_at(secret, now // 30)
    counter = totp.matching_counter(secret, code, None, now=now)
    assert totp.matching_counter(secret, code, counter, now=now) is None


def test_secret_encryption_round_trip_and_tamper_detection():
    secret = totp.new_secret()
    stored = totp.encrypt_secret(secret)
    assert secret not in stored
    assert totp.decrypt_secret(stored) == secret
    assert totp.decrypt_secret(stored[:-4] + "AAAA") is None


def test_provisioning_uri_is_what_authenticator_apps_read():
    uri = totp.provisioning_uri("ABC", "+8801000000001")
    assert uri.startswith("otpauth://totp/GRS:%2B8801000000001?secret=ABC&issuer=GRS")
