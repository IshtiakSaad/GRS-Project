import pytest

from apps.collab.scanning import EICAR, EicarScanner, detect_type


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"%PDF-1.7\n", "application/pdf"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00", "image/png"),
        (b"PK\x03\x04", None),  # zip, docx, xlsx
        (b"MZ\x90\x00", None),  # Windows executable
        (b"<html>", None),
        (b"", None),
    ],
)
def test_the_type_comes_from_the_first_bytes(head, expected):
    assert detect_type(head) == expected


def _scan(*chunks) -> str | None:
    scanner = EicarScanner()
    for chunk in chunks:
        scanner.feed(chunk)
    return scanner.verdict()


def test_the_scanner_finds_the_test_file_anywhere():
    assert _scan(b"%PDF-1.4 " + EICAR) == "Eicar-Test-Signature"
    assert _scan(b"clean bytes", b"more clean bytes") is None


@pytest.mark.parametrize("cut", [1, 10, 34, len(EICAR) - 1])
def test_the_scanner_finds_it_split_across_chunks(cut):
    assert _scan(b"x" * 100 + EICAR[:cut], EICAR[cut:] + b"y" * 100) is not None
