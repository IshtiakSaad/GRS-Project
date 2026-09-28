"""File checks that do not trust the uploader: the type comes from the file's first bytes, and a
malware scanner reads every byte.

The scanner is an interface (feed chunks, then ask for a verdict) so that ClamAV can replace the
fake without touching the verifier. The fake flags the EICAR test file, the industry-standard
harmless string every antivirus product detects, so the rejection path is testable anywhere.
"""

import base64

from django.conf import settings
from django.utils.module_loading import import_string

# Types a citizen needs for documents and photos of documents. Office files and archives are
# refused: they carry macros and nested content that a scanner may not see into.
SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
ALLOWED_TYPES = tuple(SIGNATURES)
SNIFF_BYTES = 8


def detect_type(head: bytes) -> str | None:
    for content_type, magics in SIGNATURES.items():
        if any(head.startswith(m) for m in magics):
            return content_type
    return None


class Scanner:
    """Feed the file in order; `verdict()` is None when clean, else the threat's name."""

    def feed(self, chunk: bytes) -> None:
        raise NotImplementedError

    def verdict(self) -> str | None:
        raise NotImplementedError


# Kept encoded so the source file itself is never flagged by an antivirus on a developer's disk.
EICAR = base64.b64decode(
    "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
)


class EicarScanner(Scanner):
    """The local stand-in for ClamAV: finds the EICAR string anywhere, even across chunks."""

    def __init__(self):
        self._tail = b""
        self._found = False

    def feed(self, chunk: bytes) -> None:
        window = self._tail + chunk
        if EICAR in window:
            self._found = True
        self._tail = window[-(len(EICAR) - 1) :]

    def verdict(self) -> str | None:
        return "Eicar-Test-Signature" if self._found else None


def new_scanner() -> Scanner:
    return import_string(settings.ATTACHMENT_SCANNER)()
