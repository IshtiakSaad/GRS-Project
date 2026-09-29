"""The monitor: every minute, read the edge log, compute the service level indicators, run the
checks, and alert. Runs as its own process (the `monitor` service), not as a Celery task, so it
keeps working when the broker, the workers or the database are the thing that broke.

    python manage.py monitor               # forever
    python manage.py monitor --once        # one pass, print the findings
    python manage.py monitor --test-alert  # send one message to check the phone receives it
"""

import json
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.monitoring import alerts, checks
from apps.monitoring.sli import Recorder

logger = logging.getLogger("grs.monitor")

INTERVAL = 60


class Command(BaseCommand):
    help = "Watch the service level indicators and dependencies; alert through ntfy."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--test-alert", action="store_true")

    def handle(self, *args, **options):
        send = alerts.ntfy(settings.NTFY_URL) if settings.NTFY_URL else alerts.log_only
        source = settings.MONITOR_SOURCE
        if options["test_alert"]:
            ok = send(f"test alert from {source}", "Alerts reach this phone.", "warning")
            self.stdout.write("sent" if ok else "not sent: see the error above")
            return
        recorder = Recorder(settings.MONITOR_EDGE_LOG)
        alerter = alerts.Alerter(send, source)
        while True:
            started = time.monotonic()
            self.one_pass(recorder, alerter, verbose=options["once"])
            if options["once"]:
                return
            time.sleep(max(1.0, INTERVAL - (time.monotonic() - started)))

    def one_pass(self, recorder: Recorder, alerter: alerts.Alerter, verbose: bool) -> None:
        now = timezone.now()
        recorder.read(now)
        findings = checks.run_all(recorder)
        alerter.update(findings, now)
        hour = recorder.window(now, timedelta(hours=1))
        quarter = recorder.window(now, timedelta(minutes=15))
        # The indicators themselves, one line a minute: the log is the record of the SLIs.
        sli = {
            "availability_1h": round(1 - hour.error_ratio, 5) if hour.requests else None,
            "requests_1h": hour.requests,
            "p95_15m": quarter.p95,
            "firing": sorted(f.name for f in findings if f.firing),
        }
        logger.info("sli %s", json.dumps(sli))
        if verbose:
            for f in findings:
                self.stdout.write(f"{'FIRING' if f.firing else 'ok':7} {f.name:24} {f.summary}")
