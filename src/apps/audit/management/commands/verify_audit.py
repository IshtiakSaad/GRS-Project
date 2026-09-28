from django.core.management.base import BaseCommand, CommandError

from apps.audit import sealing


class Command(BaseCommand):
    help = "Check the audit log's hash chain and anchors. Exits non-zero if broken."

    def handle(self, *args, **options):
        verdict = sealing.verify()
        if not verdict.ok:
            raise CommandError(
                f"audit chain broken at seal_seq {verdict.broken_at}: {verdict.reason} "
                f"({verdict.checked} rows checked before it)"
            )
        self.stdout.write(f"audit chain intact: {verdict.checked} rows")
