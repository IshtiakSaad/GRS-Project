"""Text normalisation for input typed on Bangla keyboards."""

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def ascii_digits(value: str) -> str:
    """Bangla digits (০-৯) become ASCII; everything else is unchanged."""
    return value.translate(_BANGLA_DIGITS)
