"""What the monitor checks each minute. Every check returns a Finding: firing or not, and one
line a person can act on.

Targets come from the design: 99.5% of API requests succeed per month (N1), p95 under 1 s
(N2), status messages delivered within 15 minutes (N3). Availability alerts use the standard
multi-window burn rates: page when the monthly error budget would be gone in about 2 days
(fast) or 5 days (slow), and only while the short window confirms it is still happening.
"""

import shutil
import socket
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Min, Q
from django.utils import timezone

from .sli import Recorder

AVAILABILITY_TARGET = 0.995
BUDGET = 1 - AVAILABILITY_TARGET
LATENCY_TARGET = 1.0
DELIVERY_TARGET = timedelta(minutes=15)

# (name, burn rate, long window, short window, minimum requests in the long window)
BURN_RULES = (
    ("availability_fast_burn", 14.4, timedelta(hours=1), timedelta(minutes=5), 20),
    ("availability_slow_burn", 6.0, timedelta(hours=6), timedelta(minutes=30), 50),
)

CRITICAL, WARNING = "critical", "warning"


@dataclass(frozen=True)
class Finding:
    name: str
    severity: str
    firing: bool
    summary: str


def availability(recorder: Recorder, now: datetime) -> list[Finding]:
    findings = []
    for name, rate, long, short, minimum in BURN_RULES:
        whole, recent = recorder.window(now, long), recorder.window(now, short)
        limit = rate * BUDGET
        firing = (
            whole.requests >= minimum and whole.error_ratio > limit and recent.error_ratio > limit
        )
        findings.append(
            Finding(
                name,
                CRITICAL,
                firing,
                f"{whole.error_ratio:.1%} of {whole.requests} API requests failed in the last "
                f"{_span(long)} ({recent.error_ratio:.1%} in the last {_span(short)}); "
                f"limit {limit:.1%}",
            )
        )
    return findings


def latency(recorder: Recorder, now: datetime) -> Finding:
    window = recorder.window(now, timedelta(minutes=15))
    p95 = window.p95
    firing = window.requests >= 50 and p95 is not None and p95 > LATENCY_TARGET
    shown = "no traffic" if p95 is None else f"p95 up to {p95:g} s"
    return Finding(
        "latency",
        WARNING,
        firing,
        f"{shown} over {window.requests} API requests in 15 min; target {LATENCY_TARGET:g} s",
    )


def readiness(url: str) -> Finding:
    """The whole path a citizen uses (Nginx, TLS, app, database), from inside the host."""
    try:
        if not url.startswith(("https://", "http://")):
            raise ValueError("not an http(s) URL")
        with urllib.request.urlopen(url, timeout=5) as reply:  # noqa: S310 - scheme checked
            ok, detail = reply.status == 200, f"HTTP {reply.status}"
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        ok, detail = False, str(exc)[:200]
    return Finding("site_down", CRITICAL, not ok, f"{url}: {detail}")


def late_notifications(now: datetime) -> Finding:
    """Status and action messages still waiting to be sent, older than the delivery target."""
    from apps.notifications.models import DeliveryStatus, Kind, Notification

    oldest = (
        Notification.objects.filter(
            status__in=[DeliveryStatus.PENDING, DeliveryStatus.LEASED],
            kind__in=[Kind.STATUS, Kind.ACTION_REQUIRED],
            created_at__gte=now - timedelta(days=2),  # recent partitions only
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .aggregate(oldest=Min("created_at"))["oldest"]
    )
    if oldest is None:
        return Finding("notifications_late", CRITICAL, False, "no messages waiting")
    age = now - oldest
    return Finding(
        "notifications_late",
        CRITICAL,
        age > DELIVERY_TARGET,
        f"oldest unsent message is {_span(age)} old; target {_span(DELIVERY_TARGET)}",
    )


def stuck_attachments(now: datetime) -> Finding:
    """Uploads waiting over 30 minutes for their check: the scanner or storage is down."""
    from apps.collab.models import Attachment, AttachmentStatus

    count = Attachment.objects.filter(
        status=AttachmentStatus.VERIFYING, created_at__lt=now - timedelta(minutes=30)
    ).count()
    return Finding(
        "attachments_stuck",
        WARNING,
        count > 0,
        f"{count} uploaded files unverified for over 30 min (scanner or storage down?)"
        if count
        else "no uploads waiting on their check",
    )


def pending_anchors(now: datetime) -> Finding:
    """Audit checkpoints not yet copied off the host: tamper evidence is weakened meanwhile."""
    from apps.audit.models import AuditAnchor

    count = AuditAnchor.objects.filter(
        stored_at__isnull=True, created_at__lt=now - timedelta(minutes=10)
    ).count()
    return Finding(
        "audit_anchors_pending",
        WARNING,
        count > 0,
        f"{count} audit checkpoints not copied off the host for over 10 min"
        if count
        else "audit checkpoints copied off the host",
    )


def wal_archiving(now: datetime) -> Finding:
    """PostgreSQL shipping WAL off the host. While it fails, segments pile up on this disk and
    the minute-level recovery point is lost; PostgreSQL retries, so this clears on its own."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_archived_time, last_failed_time, last_failed_wal FROM pg_stat_archiver"
        )
        archived, failed, failed_wal = cursor.fetchone()
    failing = failed is not None and (archived is None or failed > archived)
    if failing:
        summary = f"WAL archiving failing since {_span(now - failed)} ago (segment {failed_wal})"
    elif archived is None:
        summary = "no WAL archived yet"
    else:
        summary = f"last WAL segment shipped {_span(now - archived)} ago"
    return Finding("wal_archiving", CRITICAL, failing, summary)


def database(now: datetime) -> Finding:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return Finding("database_down", CRITICAL, False, "database answers")
    except Exception as exc:  # noqa: BLE001
        connection.close()  # a fresh connection next time
        return Finding("database_down", CRITICAL, True, f"database unreachable: {exc}"[:240])


def disk(path: str) -> Finding:
    usage = shutil.disk_usage(path)
    used = usage.used / usage.total
    return Finding(
        "disk_full", CRITICAL, used > 0.85, f"disk {used:.0%} used, {usage.free >> 30} GB free"
    )


def certificate(host: str, now: datetime) -> Finding:
    """Days until the TLS certificate expires; renewal runs twice a day, so under 14 means it
    has been failing for weeks."""
    try:
        context = ssl.create_default_context()
        with (
            socket.create_connection((host, 443), timeout=5) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            not_after = ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"])
        days = (datetime.fromtimestamp(not_after, UTC) - now).days
        firing, summary = days < 14, f"certificate expires in {days} days"
    except Exception as exc:  # noqa: BLE001 - a failed check is itself worth knowing
        firing, summary = True, f"certificate check failed: {exc}"[:240]
    return Finding("certificate_expiring", WARNING, firing, summary)


def run_all(recorder: Recorder) -> list[Finding]:
    now = timezone.now()
    findings = [*availability(recorder, now), latency(recorder, now)]
    findings.append(readiness(settings.MONITOR_READY_URL))
    db = database(now)
    findings.append(db)
    if not db.firing:
        findings += [
            late_notifications(now),
            stuck_attachments(now),
            pending_anchors(now),
            wal_archiving(now),
        ]
    findings.append(disk(settings.MONITOR_DISK_PATH))
    if settings.MONITOR_TLS_HOST:
        findings.append(certificate(settings.MONITOR_TLS_HOST, now))
    return findings


def _span(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if not rest else f"{hours} h {rest} min"
