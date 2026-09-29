"""The monitor's checks against the real database and a real HTTP server."""

import http.server
import threading
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditAnchor
from apps.collab.models import Attachment
from apps.common.ids import uuid7
from apps.monitoring import checks
from apps.notifications.models import Notification
from tests import factories as f

pytestmark = pytest.mark.django_db


def _notification(age: timedelta, **kw) -> Notification:
    n = Notification.objects.create(
        recipient=f.citizen(), channel="SMS", kind="STATUS", template="status_changed", **kw
    )
    Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - age)
    return n


def test_a_status_message_waiting_past_15_minutes_fires():
    now = timezone.now()
    _notification(timedelta(minutes=3))
    assert not checks.late_notifications(now).firing
    _notification(timedelta(minutes=20))
    finding = checks.late_notifications(now)
    assert finding.firing
    assert "unsent message is 19 min old" in finding.summary or "20 min old" in finding.summary


def test_sent_and_expired_messages_are_not_late():
    now = timezone.now()
    _notification(timedelta(minutes=40), status="SENT")
    _notification(timedelta(minutes=40), expires_at=now - timedelta(minutes=1))
    assert not checks.late_notifications(now).firing


def test_files_unverified_for_30_minutes_fire():
    request = f.draft()
    attachment = Attachment.objects.create(
        request=request,
        uploaded_by=request.owner,
        original_name="id.jpg",
        declared_content_type="image/jpeg",
        declared_size=1000,
        storage_key=f"k/{uuid7()}",
        status="VERIFYING",
    )
    assert not checks.stuck_attachments(timezone.now()).firing
    Attachment.objects.filter(pk=attachment.pk).update(
        created_at=timezone.now() - timedelta(minutes=31)
    )
    assert checks.stuck_attachments(timezone.now()).firing


def test_audit_checkpoints_not_copied_off_the_host_fire():
    AuditAnchor.objects.create(
        first_seal_seq=1,
        last_seal_seq=10,
        last_row_hash="a" * 64,
        object_key=f"anchors/{uuid7()}",
        created_at=timezone.now() - timedelta(minutes=11),
    )
    assert checks.pending_anchors(timezone.now()).firing


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        code = 200

        def do_GET(self):
            self.send_response(Handler.code)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield Handler, f"http://127.0.0.1:{server.server_address[1]}/health/ready"
    server.shutdown()


def test_the_site_is_down_when_readiness_fails(http_server):
    handler, url = http_server
    assert not checks.readiness(url).firing
    handler.code = 503
    assert checks.readiness(url).firing
    assert checks.readiness("http://127.0.0.1:9/health/ready").firing
    assert checks.readiness("file:///etc/passwd").firing  # only http(s) is ever fetched


def test_one_pass_reports_every_check(http_server, tmp_path, capsys):
    _, url = http_server
    with override_settings(
        MONITOR_READY_URL=url,
        MONITOR_EDGE_LOG=str(tmp_path / "missing.json"),
        MONITOR_DISK_PATH=str(tmp_path),
        NTFY_URL="",
    ):
        call_command("monitor", "--once")
    out = capsys.readouterr().out
    for name in (
        "availability_fast_burn",
        "availability_slow_burn",
        "latency",
        "site_down",
        "database_down",
        "notifications_late",
        "attachments_stuck",
        "audit_anchors_pending",
        "wal_archiving",
        "disk_full",
    ):
        assert name in out
    # WAL archiving reflects the real server this runs against (in CI's test job nothing creates
    # the bucket, so it rightly fires); every other check is about this test's own state.
    firing = [line for line in out.splitlines() if line.startswith("FIRING")]
    assert [line for line in firing if "wal_archiving" not in line] == []


def test_wal_archiving_reports_what_postgresql_says():
    finding = checks.wal_archiving(timezone.now())
    assert finding.name == "wal_archiving"
    assert "WAL" in finding.summary
