"""The monitor's arithmetic and alert behaviour, without a server: log lines in, findings and
messages out."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from apps.monitoring import checks
from apps.monitoring.alerts import REMIND_EVERY, Alerter
from apps.monitoring.checks import Finding
from apps.monitoring.sli import Recorder, parse

NOW = datetime(2026, 9, 29, 12, 0, 30, tzinfo=UTC)


def line(uri="/api/v1/requests", status=200, rt=0.08, at=NOW - timedelta(minutes=1)) -> str:
    return json.dumps({"ts": at.isoformat(), "uri": uri, "status": status, "rt": rt}) + "\n"


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "edge.json"
    path.write_text("")
    return path


def write(path, *lines):
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines)


def test_only_api_requests_count():
    assert parse(line())[1:] == (200, 0.08)
    assert parse(line(uri="/health/ready")) is None  # the monitor's own checks
    assert parse(line(uri="/_next/static/app.js")) is None
    assert parse(line(status=499)) is None  # the client gave up
    assert parse("not json") is None
    assert parse('{"ts": "2026-09-29T12:00:00+00:00", "uri": "/api/x"}') is None


def test_windows_count_errors_and_latency(log):
    write(log, *[line() for _ in range(90)], *[line(status=503, rt=2.5) for _ in range(10)])
    recorder = Recorder(str(log))
    assert recorder.read(NOW) == 100
    window = recorder.window(NOW, timedelta(minutes=5))
    assert (window.requests, window.errors) == (100, 10)
    assert window.error_ratio == pytest.approx(0.10)
    assert window.p95 == 5.0  # the 2.5 s requests sit in the (2, 5] bucket
    assert recorder.window(NOW, timedelta(minutes=5)).requests == 100  # reading is idempotent


def test_429_is_not_an_error(log):
    write(log, *[line(status=429) for _ in range(30)])
    recorder = Recorder(str(log))
    recorder.read(NOW)
    assert recorder.window(NOW, timedelta(minutes=5)).errors == 0


def test_the_current_minute_is_left_out(log):
    write(log, line(at=NOW))
    recorder = Recorder(str(log))
    recorder.read(NOW)
    assert recorder.window(NOW, timedelta(minutes=5)).requests == 0


def test_a_half_written_line_is_read_whole_next_time(log):
    full = line()
    write(log, full, full[:20])
    recorder = Recorder(str(log))
    assert recorder.read(NOW) == 1
    write(log, full[20:])
    assert recorder.read(NOW) == 1
    assert recorder.window(NOW, timedelta(minutes=5)).requests == 2


def test_it_follows_the_log_across_rotation(log):
    write(log, line(), line())
    recorder = Recorder(str(log))
    recorder.read(NOW)
    os.replace(log, str(log) + ".1")
    write(log, line())
    assert recorder.read(NOW) == 1
    assert recorder.window(NOW, timedelta(minutes=5)).requests == 3


def test_old_minutes_are_dropped(log):
    write(log, line(at=NOW - timedelta(hours=7)), line())
    recorder = Recorder(str(log))
    recorder.read(NOW)
    assert len(recorder.buckets) == 1


def _recorder_with(log, ok_per_min: int, errors_per_min: int, minutes: int) -> Recorder:
    lines = []
    for m in range(1, minutes + 1):
        at = NOW - timedelta(minutes=m)
        lines += [line(at=at)] * ok_per_min + [line(status=500, at=at)] * errors_per_min
    write(log, *lines)
    recorder = Recorder(str(log))
    recorder.read(NOW)
    return recorder


def _firing(findings, name):
    return next(f for f in findings if f.name == name).firing


def test_a_fast_error_burn_pages(log):
    recorder = _recorder_with(log, ok_per_min=9, errors_per_min=1, minutes=60)  # 10% failing
    findings = checks.availability(recorder, NOW)
    assert _firing(findings, "availability_fast_burn")
    assert _firing(findings, "availability_slow_burn")


def test_errors_that_have_stopped_do_not_page(log):
    """Only errors in the last hour's first 50 minutes: the 5-minute window shows recovery."""
    lines = []
    for m in range(6, 61):
        lines += [line(status=500, at=NOW - timedelta(minutes=m))]
    for m in range(1, 6):
        lines += [line(at=NOW - timedelta(minutes=m))] * 10
    write(log, *lines)
    recorder = Recorder(str(log))
    recorder.read(NOW)
    assert not _firing(checks.availability(recorder, NOW), "availability_fast_burn")


def test_a_few_requests_are_not_enough_to_page(log):
    recorder = _recorder_with(log, ok_per_min=0, errors_per_min=1, minutes=10)  # all failing
    assert not _firing(checks.availability(recorder, NOW), "availability_fast_burn")


def test_healthy_traffic_is_quiet(log):
    recorder = _recorder_with(log, ok_per_min=50, errors_per_min=0, minutes=60)
    assert not any(f.firing for f in checks.availability(recorder, NOW))
    assert not checks.latency(recorder, NOW).firing


def test_slow_responses_warn(log):
    write(log, *[line(rt=1.8, at=NOW - timedelta(minutes=m % 10 + 1)) for m in range(60)])
    recorder = Recorder(str(log))
    recorder.read(NOW)
    finding = checks.latency(recorder, NOW)
    assert finding.firing
    assert "p95 up to 2 s" in finding.summary


class Phone:
    def __init__(self, up=True):
        self.up = up
        self.received: list[tuple[str, str]] = []

    def __call__(self, title, message, severity):
        if self.up:
            self.received.append((title, severity))
        return self.up


def _down(firing=True):
    return [Finding("site_down", checks.CRITICAL, firing, "HTTP 502")]


def test_an_alert_is_sent_once_then_reminded_then_cleared():
    phone = Phone()
    alerter = Alerter(phone, "grs.example")
    alerter.update(_down(), NOW)
    alerter.update(_down(), NOW + timedelta(minutes=1))
    assert phone.received == [("site_down on grs.example", "critical")]
    alerter.update(_down(), NOW + REMIND_EVERY)
    assert phone.received[-1] == ("still: site_down on grs.example", "critical")
    alerter.update(_down(firing=False), NOW + REMIND_EVERY + timedelta(minutes=1))
    assert phone.received[-1] == ("resolved: site_down on grs.example", "resolved")
    alerter.update(_down(firing=False), NOW + REMIND_EVERY + timedelta(minutes=2))
    assert len(phone.received) == 3


def test_nothing_is_sent_while_all_is_well():
    phone = Phone()
    Alerter(phone, "x").update(_down(firing=False), NOW)
    assert phone.received == []


def test_an_alert_that_could_not_be_sent_is_retried():
    phone = Phone(up=False)
    alerter = Alerter(phone, "x")
    alerter.update(_down(), NOW)
    phone.up = True
    alerter.update(_down(), NOW + timedelta(minutes=1))
    assert phone.received == [("site_down on x", "critical")]


def test_a_clear_is_sent_only_for_an_alert_that_was_sent():
    phone = Phone(up=False)
    alerter = Alerter(phone, "x")
    alerter.update(_down(), NOW)  # never delivered
    phone.up = True
    alerter.update(_down(firing=False), NOW + timedelta(minutes=1))
    assert phone.received == []
