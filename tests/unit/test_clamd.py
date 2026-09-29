"""The ClamAV client against a stand-in daemon that speaks clamd's INSTREAM protocol. CI also
runs the real ClamAV image against the same client (the `clamav` job)."""

import os
import socket
import struct
import threading

import pytest
from django.test import override_settings

from apps.collab.scanning import EICAR, ClamdScanner, ScannerUnavailable


class FakeClamd:
    """Accepts one INSTREAM session per connection, reassembles the chunks, and replies with
    `reply(data)`. Records what it received."""

    def __init__(self, reply):
        self.reply = reply
        self.received: list[bytes] = []
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _read(self, conn, n: int) -> bytes:
        data = b""
        while len(data) < n:
            part = conn.recv(n - len(data))
            if not part:
                raise ConnectionError
            data += part
        return data

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                assert self._read(conn, 10) == b"zINSTREAM\0"
                data = b""
                while size := struct.unpack(">I", self._read(conn, 4))[0]:
                    data += self._read(conn, size)
                self.received.append(data)
                conn.sendall(self.reply(data))

    def close(self):
        self.server.close()


@pytest.fixture
def clamd():
    servers = []

    def start(reply):
        server = FakeClamd(reply)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _scan(port: int, *chunks: bytes) -> str | None:
    with override_settings(CLAMD_HOST="127.0.0.1", CLAMD_PORT=port, CLAMD_TIMEOUT=2):
        scanner = ClamdScanner()
        try:
            for chunk in chunks:
                scanner.feed(chunk)
            return scanner.verdict()
        finally:
            scanner.close()


def _like_clamav(data: bytes) -> bytes:
    return b"stream: Win.Test.EICAR_HDB-1 FOUND\0" if EICAR in data else b"stream: OK\0"


def test_a_clean_file_is_streamed_whole_and_passes(clamd):
    server = clamd(_like_clamav)
    assert _scan(server.port, b"%PDF-1.4 ", b"", b"clean") is None
    assert server.received == [b"%PDF-1.4 clean"]


def test_a_found_threat_is_named(clamd):
    server = clamd(_like_clamav)
    assert _scan(server.port, b"%PDF ", EICAR[:20], EICAR[20:]) == "Win.Test.EICAR_HDB-1"


def test_an_empty_file_is_still_scanned(clamd):
    server = clamd(_like_clamav)
    assert _scan(server.port) is None
    assert server.received == [b""]


@pytest.mark.parametrize(
    "reply",
    [b"INSTREAM size limit exceeded. ERROR\0", b"stream: lstat() failed ERROR\0", b""],
)
def test_anything_but_a_verdict_is_not_a_pass(clamd, reply):
    server = clamd(lambda data: reply)
    with pytest.raises(ScannerUnavailable):
        _scan(server.port, b"%PDF-1.4 data")


def test_a_daemon_that_is_down_is_not_a_pass():
    with socket.create_server(("127.0.0.1", 0)) as spare:
        port = spare.getsockname()[1]  # closed on exit: nothing listens there
    with pytest.raises(ScannerUnavailable):
        _scan(port, b"%PDF-1.4 data")


@pytest.mark.skipif(not os.environ.get("CLAMD_LIVE_HOST"), reason="set CLAMD_LIVE_HOST")
def test_the_real_daemon():
    """Against real ClamAV (CI's `clamav` job): the test file is found, a clean one passes."""
    host, port = os.environ["CLAMD_LIVE_HOST"], int(os.environ.get("CLAMD_LIVE_PORT", "3310"))
    with override_settings(CLAMD_HOST=host, CLAMD_PORT=port, CLAMD_TIMEOUT=30):
        for content, clean in [(EICAR, False), (b"%PDF-1.4 hello", True)]:
            scanner = ClamdScanner()
            for i in range(0, len(content), 7):  # small chunks: the stream must reassemble
                scanner.feed(content[i : i + 7])
            assert (scanner.verdict() is None) == clean
