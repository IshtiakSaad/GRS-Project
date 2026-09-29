from django.core.management.base import BaseCommand

from apps.audit import offsite


class Command(BaseCommand):
    help = "Create the off-host bucket (versioned, Object Lock) if missing; check it if present."

    def handle(self, *args, **options):
        self.stdout.write(f"off-host bucket: {offsite.ensure_bucket()}")
