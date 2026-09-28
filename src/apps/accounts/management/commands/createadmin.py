"""Create an administrator, on the host only (design §4.2: no API can create the first admin).

    docker compose run --rm migrate python manage.py createadmin --phone 01000000001 --name "…"

The password is read from the terminal (or GRS_ADMIN_PASSWORD for scripted setups), never from
the command line, where it would land in shell history and the process list. The command
prints the two-step login secret and recovery codes once; they are not stored readable.
"""

import getpass
import os

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import services, totp
from apps.accounts.models import User
from apps.common.errors import AppError
from apps.common.phone import normalise_phone


class Command(BaseCommand):
    help = "Create an administrator with two-step login enrolled."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args, phone, name, **options):
        number = normalise_phone(phone)
        if number is None:
            raise CommandError("not an accepted mobile number")
        if User.objects.filter(phone=number).exists():
            raise CommandError("an account with this phone already exists")
        password = os.environ.get("GRS_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        try:
            user, secret, codes = services.create_admin(number, name, password)
        except AppError as exc:
            raise CommandError(f"{exc.detail}: {exc.fields}") from exc

        self.stdout.write(f"Administrator {user.public_id} created.")
        self.stdout.write("Add this to an authenticator app (shown once):")
        self.stdout.write(f"  {totp.provisioning_uri(secret, number)}")
        self.stdout.write("Recovery codes, one use each (shown once):")
        for code in codes:
            self.stdout.write(f"  {code}")
