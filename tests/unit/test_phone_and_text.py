import pytest

from apps.common.phone import normalise_phone
from apps.common.text import clean_text


@pytest.mark.parametrize(
    "raw",
    [
        "01012345678",
        "+8801012345678",
        "8801012345678",
        "008801012345678",
        "010-1234-5678",
        " 010 1234 5678 ",
        "০১০১২৩৪৫৬৭৮",  # Bangla digits, as typed on a Bangla keyboard
        "+৮৮০ ১০১২ ৩৪৫৬৭৮",
    ],
)
def test_demo_number_in_any_common_form(raw, settings):
    settings.DEMO_MODE = True
    assert normalise_phone(raw) == "+8801012345678"


@pytest.mark.parametrize(
    "raw",
    ["", "0171234567", "017123456789", "+8801212345678", "+9101712345678", "abc", "0" * 40, None],
)
def test_rejects_what_is_not_a_mobile_number(raw, settings):
    settings.DEMO_MODE = False
    assert normalise_phone(raw) is None


def test_demo_mode_refuses_real_numbers_and_live_mode_refuses_demo_ones(settings):
    settings.DEMO_MODE = True
    assert normalise_phone("01712345678") is None  # no real person can be messaged by the demo
    settings.DEMO_MODE = False
    assert normalise_phone("01712345678") == "+8801712345678"
    assert normalise_phone("01012345678") is None


def test_arabic_indic_digits_are_not_bangla_digits(settings):
    settings.DEMO_MODE = True
    assert normalise_phone("٠١٠١٢٣٤٥٦٧٨") is None


def test_clean_text_makes_equal_bangla_equal():
    decomposed = "কো"  # ক + ে + া  (two code points for the vowel sign)
    composed = "কো"  # ক + ো
    assert clean_text(decomposed) == clean_text(composed) == composed


def test_clean_text_drops_control_characters_but_keeps_bangla_joiners():
    assert clean_text("  a\x00b‮c  ") == "abc"  # NUL and a right-to-left override
    assert clean_text("ক্‌ষ") == "ক্‌ষ"  # ZWNJ chooses the letters over the conjunct
    assert clean_text("line1\r\nline2", multiline=True) == "line1\nline2"
    assert clean_text("line1\nline2") == "line1line2"
