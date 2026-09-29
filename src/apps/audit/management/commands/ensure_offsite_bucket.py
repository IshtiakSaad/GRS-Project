import sys

from django.core.management.base import BaseCommand

from apps.audit import offsite


class Command(BaseCommand):
    help = (
        "Create the off-host bucket (versioned, Object Lock) if missing; check it if present. "
        "Never fails the start-up: if the store is unreachable, anchors and WAL wait for it."
    )

    def handle(self, *args, **options):
        try:
            self.stdout.write(f"off-host bucket: {offsite.ensure_bucket()}")
        except Exception as exc:  # noqa: BLE001 - reported, and the monitor keeps watching
            sys.stderr.write(f"WARNING off-host bucket not ready: {exc}\n")
