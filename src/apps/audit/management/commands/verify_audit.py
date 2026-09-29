from django.core.management.base import BaseCommand, CommandError

from apps.audit import sealing


class Command(BaseCommand):
    help = (
        "Check the audit log's hash chain against its anchors, including the locked copies "
        "off the host. Exits non-zero if broken or if the off-host store cannot be read."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--restored-copy",
            action="store_true",
            help="the database is a restored backup: off-host anchors newer than it are expected",
        )
        parser.add_argument(
            "--local-only",
            action="store_true",
            help="skip the off-host copies (weaker: the database's own anchors can be rewritten)",
        )

    def handle(self, *args, **options):
        try:
            verdict = sealing.verify(
                offsite_check=not options["local_only"], allow_newer=options["restored_copy"]
            )
        except sealing.OffsiteUnavailable as exc:
            raise CommandError(f"could not read the off-host anchors: {exc}") from exc
        if not verdict.ok:
            raise CommandError(
                f"audit chain broken at seal_seq {verdict.broken_at}: {verdict.reason} "
                f"({verdict.checked} rows checked before it)"
            )
        where = "the database's anchors" if options["local_only"] else "its off-host anchors"
        self.stdout.write(f"audit chain intact: {verdict.checked} rows, checked against {where}")
