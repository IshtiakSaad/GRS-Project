"""File checks that do not trust the uploader: the type comes from the file's first bytes, and a
malware scanner reads every byte.

The scanner is an interface (feed chunks, then ask for a verdict). Production uses ClamAV
(`ClamdScanner`); the local default is a fake that flags the EICAR test file, the
industry-standard harmless string every antivirus product detects, so the rejection path is
testable anywhere without a 1 GB signature database.
"""

import base64
import socket
import struct

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


class ScannerUnavailable(Exception):
    """The scanner could not give a verdict. The file stays unverified and is retried later:
    a file is never approved without a scan."""


class Scanner:
    """Feed the file in order; `verdict()` is None when clean, else the threat's name."""

    def feed(self, chunk: bytes) -> None:
        raise NotImplementedError

    def verdict(self) -> str | None:
        raise NotImplementedError

    def close(self) -> None:
        """Release anything held; called whether or not a verdict was asked for."""


# Kept encoded so the source file itself is never flagged by an antivirus on a developer's disk.
EICAR = base64.b64decode(
    "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
)


class EicarScanner(Scanner):
    """The local stand-in for ClamAV. It flags what ClamAV flags as the test file: a file that
    starts with the EICAR string (the EICAR standard; ClamAV ignores the string elsewhere)."""

    def __init__(self):
        self._head = b""

    def feed(self, chunk: bytes) -> None:
        if len(self._head) < len(EICAR):
            self._head += chunk[: len(EICAR) - len(self._head)]

    def verdict(self) -> str | None:
        return "Eicar-Test-Signature" if self._head == EICAR else None


class ClamdScanner(Scanner):
    """ClamAV's daemon over TCP, INSTREAM command: the file is streamed as it is read from
    storage, so it is never held in memory or written to the worker's disk.

    Protocol: `zINSTREAM\\0`, then chunks each prefixed with a 4-byte big-endian length, then a
    zero length. The reply is `stream: OK` or `stream: <name> FOUND`; anything else (including
    `INSTREAM size limit exceeded`) is not a verdict.
    """

    def __init__(self):
        self._sock: socket.socket | None = None

    def _connect(self) -> socket.socket:
        if self._sock is None:
            try:
                self._sock = socket.create_connection(
                    (settings.CLAMD_HOST, settings.CLAMD_PORT), timeout=settings.CLAMD_TIMEOUT
                )
                self._sock.sendall(b"zINSTREAM\0")
            except OSError as exc:
                self.close()
                raise ScannerUnavailable(f"clamd unreachable: {exc}") from exc
        return self._sock

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return  # a zero length would end the stream early
        sock = self._connect()
        try:
            sock.sendall(struct.pack(">I", len(chunk)) + chunk)
        except OSError as exc:
            self.close()
            raise ScannerUnavailable(f"clamd dropped the stream: {exc}") from exc

    def verdict(self) -> str | None:
        sock = self._connect()  # an empty file is still scanned
        try:
            sock.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
        except OSError as exc:
            raise ScannerUnavailable(f"clamd gave no reply: {exc}") from exc
        finally:
            self.close()
        text = reply.rstrip(b"\0").decode(errors="replace").strip()
        if text == "stream: OK":
            return None
        if text.startswith("stream: ") and text.endswith(" FOUND"):
            return text[len("stream: ") : -len(" FOUND")]
        raise ScannerUnavailable(f"clamd: {text or 'empty reply'}")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def new_scanner() -> Scanner:
    return import_string(settings.ATTACHMENT_SCANNER)()
