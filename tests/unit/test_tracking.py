import random

import pytest

from apps.service_requests.tracking import (
    TRACKING_RE,
    damm,
    format_tracking_no,
    parse_tracking_no,
)


def test_damm_reference_value():
    # Published example: the check digit of 572 is 4, and 5724 validates to 0.
    assert damm("572") == 4
    assert damm("5724") == 0


def test_format_pads_serial_to_seven_digits():
    number = format_tracking_no(2026, 4213)
    assert number.startswith("26-0004213-")
    assert TRACKING_RE.match(number)
    assert damm(number.replace("-", "")) == 0


def test_format_widens_instead_of_failing_past_ten_million():
    number = format_tracking_no(2026, 12_345_678)
    assert number.startswith("26-12345678-")
    assert TRACKING_RE.match(number)


@pytest.mark.parametrize("serial", [0, -1])
def test_format_rejects_non_positive_serials(serial):
    with pytest.raises(ValueError):
        format_tracking_no(2026, serial)


def _samples(count=300):
    rng = random.Random(20260928)
    return [format_tracking_no(2026, rng.randint(1, 9_999_999)) for _ in range(count)]


def test_every_single_digit_error_is_caught():
    for number in _samples():
        digits = number.replace("-", "")
        for i, original in enumerate(digits):
            for wrong in "0123456789":
                if wrong != original:
                    typo = digits[:i] + wrong + digits[i + 1 :]
                    assert parse_tracking_no(typo) is None, (number, typo)


def test_every_adjacent_swap_is_caught():
    for number in _samples():
        digits = number.replace("-", "")
        for i in range(len(digits) - 1):
            if digits[i] != digits[i + 1]:
                swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
                assert parse_tracking_no(swapped) is None, (number, swapped)


def test_parse_accepts_bangla_digits_spaces_and_missing_dashes():
    number = format_tracking_no(2026, 4213)
    bangla = number.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")).replace("-", " ")
    assert parse_tracking_no(bangla) == number
    assert parse_tracking_no(number.replace("-", "")) == number


@pytest.mark.parametrize("raw", ["", "abc", "26-0004213", "26-00042-13-7x", "٢٦٠٠٠٤٢١٣٧"])
def test_parse_rejects_malformed_input(raw):
    assert parse_tracking_no(raw) is None
