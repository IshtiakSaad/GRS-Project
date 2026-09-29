"""Service level indicators from Nginx's access log.

Nginx writes one JSON line per request to a shared log file. The monitor reads new lines every
minute and folds them into per-minute buckets: request count, server errors, and a latency
histogram. Six hours of buckets are kept, which is enough for every alert window, whatever the
traffic: memory does not grow with requests.

Measured over API requests only. Health checks (the monitor's own and Docker's) and the web
app's static files would dilute the numbers. Server errors are 5xx; a 429 is the system
protecting itself, not failing.
"""

import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

# Latency bucket upper bounds, in seconds. p95 is reported as the bound of the bucket it falls
# in, so it is exact at 1 s, the target.
BOUNDS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))
KEEP = timedelta(hours=6)


@dataclass
class Bucket:
    requests: int = 0
    errors: int = 0
    latency: list[int] = field(default_factory=lambda: [0] * len(BOUNDS))

    def add(self, status: int, seconds: float) -> None:
        self.requests += 1
        if status >= 500:
            self.errors += 1
        for i, bound in enumerate(BOUNDS):
            if seconds <= bound:
                self.latency[i] += 1
                break


@dataclass
class Window:
    requests: int
    errors: int
    latency: list[int]

    @property
    def error_ratio(self) -> float:
        return self.errors / self.requests if self.requests else 0.0

    @property
    def p95(self) -> float | None:
        """Upper bound of the bucket holding the 95th percentile; None without traffic."""
        if not self.requests:
            return None
        rank, seen = 0.95 * self.requests, 0
        for bound, count in zip(BOUNDS, self.latency, strict=True):
            seen += count
            if seen >= rank:
                return bound
        return BOUNDS[-1]


def counted(line: dict) -> bool:
    uri = line.get("uri", "")
    return uri.startswith("/api/") and line.get("status") != 499  # 499: the client gave up


def parse(raw: str) -> tuple[datetime, int, float] | None:
    """(minute, status, seconds) for a line that counts, else None. Bad lines are skipped:
    a half-written last line is read again, whole, on the next pass."""
    try:
        line = json.loads(raw)
        if not counted(line):
            return None
        at = datetime.fromisoformat(line["ts"]).astimezone(UTC).replace(second=0, microsecond=0)
        return at, int(line["status"]), float(line["rt"])
    except (ValueError, KeyError, TypeError):
        return None


class Recorder:
    """Per-minute buckets fed from the log file, following it across rotations."""

    def __init__(self, path: str):
        self.path = path
        self.buckets: OrderedDict[datetime, Bucket] = OrderedDict()
        self._inode: int | None = None
        self._offset = 0

    def add(self, minute: datetime, status: int, seconds: float) -> None:
        bucket = self.buckets.get(minute)
        if bucket is None:
            bucket = self.buckets[minute] = Bucket()
            if len(self.buckets) > 1 and minute < next(reversed(self.buckets)):
                self.buckets = OrderedDict(sorted(self.buckets.items()))
        bucket.add(status, seconds)

    def read(self, now: datetime) -> int:
        """Fold in the lines written since the last call. Returns how many were read."""
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            return 0
        if stat.st_ino != self._inode or stat.st_size < self._offset:
            self._inode, self._offset = stat.st_ino, 0  # rotated or truncated: start over
        read = 0
        oldest = now - KEEP
        with open(self.path, "rb") as log:
            log.seek(self._offset)
            for raw in log:
                if not raw.endswith(b"\n"):
                    break  # Nginx is mid-write; take it next time
                self._offset += len(raw)
                read += 1
                parsed = parse(raw.decode("utf-8", errors="replace"))
                if parsed and parsed[0] >= oldest:
                    self.add(*parsed)
        self.prune(now)
        return read

    def prune(self, now: datetime) -> None:
        oldest = now - KEEP
        while self.buckets and next(iter(self.buckets)) < oldest:
            self.buckets.popitem(last=False)

    def window(self, now: datetime, length: timedelta) -> Window:
        """Totals over the last `length`, whole minutes, not counting the current one (still
        being written)."""
        end = now.astimezone(UTC).replace(second=0, microsecond=0)
        start = end - length
        total = Window(0, 0, [0] * len(BOUNDS))
        for minute, bucket in self.buckets.items():
            if start <= minute < end:
                total.requests += bucket.requests
                total.errors += bucket.errors
                total.latency = [a + b for a, b in zip(total.latency, bucket.latency, strict=True)]
        return total
