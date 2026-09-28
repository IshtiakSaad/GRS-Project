"""Synthetic citizens for load tests (loadtest/README.md). Demo mode only.

    python manage.py seed_load_users 300

Numbers +880 1099 000000 upward: the unassigned 010 prefix, like every demo account. Each one
has its own phone, so per-phone limits apply to each virtual user as they would to real people.
"""

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User

from .seed_demo import DEFAULT_PASSWORD

FIRST = 1099000000


def load_phone(i: int) -> str:
    return f"+880{FIRST + i}"


class Command(BaseCommand):
    help = "Create N verified synthetic citizens for load testing (demo mode only)."

    def add_arguments(self, parser):
        parser.add_argument("count", type=int)

    def handle(self, *args, count, **options):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE is off; load-test accounts are never created live")
        password = make_password(DEFAULT_PASSWORD)  # hash once; every account shares it
        now = timezone.now()
        users = [
            User(
                phone=load_phone(i),
                full_name=f"Load test {i}",
                password=password,
                phone_verified_at=now,
            )
            for i in range(count)
        ]
        created = User.objects.bulk_create(users, ignore_conflicts=True, batch_size=500)
        self.stdout.write(
            f"{len(created)} load-test citizens ready: {load_phone(0)} to "
            f"{load_phone(count - 1)}, password {DEFAULT_PASSWORD}"
        )
