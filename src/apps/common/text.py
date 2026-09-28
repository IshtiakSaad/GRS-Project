"""Text normalisation for input typed on Bangla keyboards."""

import unicodedata

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# Zero-width non-joiner and joiner are formatting characters, but Bangla needs them to choose
# between a conjunct and its separate letters, so they are kept.
_JOINERS = "‌‍"


def ascii_digits(value: str) -> str:
    """Bangla digits (০-৯) become ASCII; everything else is unchanged."""
    return value.translate(_BANGLA_DIGITS)


def clean_text(value: str, multiline: bool = False) -> str:
    """NFC-normalise and trim, and drop control characters.

    The same Bangla glyph can be typed as different code-point sequences; NFC makes them equal,
    so search and duplicate detection see one string. Control characters (other than newlines
    and tabs in multi-line fields) have no place in a form field and can hide text in logs.
    """
    value = unicodedata.normalize("NFC", value).strip()
    keep = _JOINERS + ("\n\t" if multiline else "")
    return "".join(c for c in value if c in keep or unicodedata.category(c)[0] != "C")
