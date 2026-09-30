"""Demo data for the local profile and the public demo. Synthetic only.

    docker compose run --rm --no-deps api python manage.py seed_demo

Every phone number is on the unassigned 010 prefix, so no real person can receive a message.
Requests are moved through the real transition engine, so the demo shows what the system does,
not rows typed into tables. Refuses to run unless DEMO_MODE is on, and runs once.
"""

import os
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts import services as accounts
from apps.accounts import totp
from apps.accounts.models import Role, User
from apps.directory.models import Category, Department, Holiday
from apps.service_requests import services, transitions

DEFAULT_PASSWORD = "demo-password-2026"  # noqa: S105 - public demo accounts, synthetic data

DEPARTMENTS = [
    ("REGISTRY", "জন্ম ও মৃত্যু নিবন্ধন", "Birth and Death Registration"),
    ("LAND", "ভূমি অফিস", "Land Office"),
    ("TRADE", "ট্রেড লাইসেন্স শাখা", "Trade Licence Section"),
]
CATEGORIES = [
    ("REGISTRY", "BIRTH_CERT_CORRECTION", "জন্ম সনদ সংশোধন", "Birth certificate correction", 7),
    ("REGISTRY", "DEATH_CERT", "মৃত্যু সনদ", "Death certificate", 5),
    ("LAND", "LAND_MUTATION", "নামজারি", "Land mutation", 28),
    ("LAND", "LAND_RECORD_COPY", "খতিয়ানের অনুলিপি", "Copy of land record", 10),
    ("TRADE", "TRADE_LICENCE_RENEWAL", "ট্রেড লাইসেন্স নবায়ন", "Trade licence renewal", 15),
]
HOLIDAYS = [
    (date(2026, 12, 16), "বিজয় দিবস", "Victory Day"),
    (date(2027, 2, 21), "শহীদ দিবস ও আন্তর্জাতিক মাতৃভাষা দিবস", "Language Martyrs' Day"),
    (date(2027, 3, 26), "স্বাধীনতা দিবস", "Independence Day"),
    (date(2027, 4, 14), "পহেলা বৈশাখ", "Bengali New Year"),
    (date(2027, 5, 1), "মে দিবস", "May Day"),
]
ADMIN = ("+8801000000001", "Demo Admin")
OFFICERS = [
    ("+8801000000011", "Nasrin Akter", "REGISTRY"),
    ("+8801000000012", "Tanvir Hasan", "REGISTRY"),
    ("+8801000000013", "Farhana Islam", "LAND"),
    ("+8801000000014", "Mizanur Rahman", "TRADE"),
]
CITIZENS = [
    ("+8801000000101", "রহিম উদ্দিন"),
    ("+8801000000102", "Salma Begum"),
    ("+8801000000103", "করিম মিয়া"),
    ("+8801000000104", "Ayesha Siddiqua"),
]


class Command(BaseCommand):
    help = "Load synthetic demo data: directory, staff, citizens and requests in every state."

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("DEMO_MODE is off; demo data is never loaded into a live system")
        if Department.objects.filter(code="REGISTRY").exists():
            self.stdout.write("Demo data is already loaded.")
            return
        password = os.environ.get("GRS_DEMO_PASSWORD") or DEFAULT_PASSWORD
        with transaction.atomic():
            self._directory()
            admin, secret, codes = accounts.create_admin(*ADMIN, password)
            officers = self._officers(password)
            citizens = self._citizens(password)
            self._requests(admin, officers, citizens)

        self.stdout.write(f"Demo data loaded. Every account's password: {password}")
        self.stdout.write(f"Administrator {ADMIN[0]}; two-step login secret (authenticator app):")
        self.stdout.write(f"  {totp.provisioning_uri(secret, ADMIN[0])}")
        self.stdout.write(f"  recovery code: {codes[0]}")
        self.stdout.write("Officers: " + ", ".join(phone for phone, _, _ in OFFICERS))
        self.stdout.write("Citizens: " + ", ".join(phone for phone, _ in CITIZENS))

    def _directory(self):
        for code, name_bn, name_en in DEPARTMENTS:
            Department.objects.create(code=code, name_bn=name_bn, name_en=name_en)
        for dept, code, name_bn, name_en, days in CATEGORIES:
            Category.objects.create(
                department=Department.objects.get(code=dept),
                code=code,
                name_bn=name_bn,
                name_en=name_en,
                target_working_days=days,
            )
        for day, name_bn, name_en in HOLIDAYS:
            Holiday.objects.get_or_create(
                date=day, defaults={"name_bn": name_bn, "name_en": name_en}
            )

    def _officers(self, password) -> dict[str, User]:
        return {
            phone: User.objects.create_user(
                phone,
                password,
                full_name=name,
                role=Role.OFFICER,
                department=Department.objects.get(code=dept),
                phone_verified_at=timezone.now(),
            )
            for phone, name, dept in OFFICERS
        }

    def _citizens(self, password) -> list[User]:
        return [
            User.objects.create_user(
                phone, password, full_name=name, phone_verified_at=timezone.now()
            )
            for phone, name in CITIZENS
        ]

    def _requests(self, admin, officers, citizens):
        rahim, salma, karim, ayesha = citizens
        nasrin, tanvir, farhana, mizan = officers.values()

        def new(owner, category, title, description, beneficiary=None, **extra):
            return services.create_draft(
                owner,
                {
                    "category": category,
                    "title": title,
                    "description": description,
                    "beneficiary": beneficiary,
                    **extra,
                },
            )

        def run(req, *steps):
            for user, action, data in steps:
                transitions.perform(user, req.public_id, action, data)

        submit = {"confirm_duplicate": False}

        new(rahim, "LAND_RECORD_COPY", "খতিয়ানের কপি", "দাগ নং ৪৫২, মৌজা কালিগঞ্জ।")  # DRAFT

        child = {"name": "তানিয়া উদ্দিন", "relation": "CHILD"}
        req = new(
            rahim,
            "BIRTH_CERT_CORRECTION",
            "জন্ম সনদে নামের বানান ভুল",
            "সনদে 'তানিয়া' এর বদলে 'তানিযা' লেখা হয়েছে।",
            child,
        )
        run(req, (rahim, "submit", submit))  # SUBMITTED

        req = new(
            salma,
            "DEATH_CERT",
            "Death certificate for my father",
            "My father passed away on 2 September 2026 at home.",
            {"name": "Abdul Karim", "relation": "PARENT"},
            citizen_urgent=True,
            urgency_reason="Needed for a bank claim this month.",
        )
        run(req, (salma, "submit", submit))  # SUBMITTED, urgent

        req = new(karim, "LAND_MUTATION", "নামজারি আবেদন", "ক্রয়সূত্রে প্রাপ্ত জমির নামজারি।")
        run(req, (karim, "submit", submit), (admin, "assign", {"officer": farhana.public_id}))

        req = new(
            ayesha,
            "TRADE_LICENCE_RENEWAL",
            "Renew licence for my shop",
            "Licence number TL-2025-0142 expires in October.",
        )
        run(
            req,
            (ayesha, "submit", submit),
            (admin, "assign", {"officer": mizan.public_id}),
            (mizan, "start", {}),
        )  # IN_PROGRESS

        req = new(
            salma,
            "BIRTH_CERT_CORRECTION",
            "Wrong date of birth",
            "The certificate shows 1990 instead of 1991.",
        )
        run(
            req,
            (salma, "submit", submit),
            (admin, "assign", {"officer": nasrin.public_id}),
            (nasrin, "start", {}),
            (
                nasrin,
                "request_info",
                {
                    "reason_code": "MISSING_DOCUMENT",
                    "message": "Please upload your school certificate.",
                },
            ),
        )

        req = new(
            rahim,
            "DEATH_CERT",
            "মৃত্যু সনদ",
            "আমার দাদার মৃত্যু সনদ প্রয়োজন।",
            {"name": "আব্দুল হামিদ", "relation": "OTHER"},
        )
        run(
            req,
            (rahim, "submit", submit),
            (admin, "assign", {"officer": tanvir.public_id}),
            (tanvir, "start", {}),
            (tanvir, "resolve", {"note": "সনদ প্রস্তুত। ইউনিয়ন পরিষদ থেকে সংগ্রহ করুন।"}),
        )

        req = new(karim, "LAND_RECORD_COPY", "খতিয়ানের অনুলিপি", "দাগ নং ১১২।")
        run(
            req,
            (karim, "submit", submit),
            (admin, "assign", {"officer": farhana.public_id}),
            (
                farhana,
                "reject",
                {"reason_code": "WRONG_OFFICE", "note": "এই মৌজার রেকর্ড জেলা রেকর্ড রুমে থাকে।"},
            ),
        )

        req = new(
            ayesha,
            "BIRTH_CERT_CORRECTION",
            "Spelling of my mother's name",
            "Mother's name should be Rokeya, not Rokeiya.",
        )
        run(
            req,
            (ayesha, "submit", submit),
            (ayesha, "withdraw", {"reason": "Corrected at the union office."}),
        )

        req = new(salma, "LAND_RECORD_COPY", "Copy of khatian 207", "For a loan application.")
        run(
            req,
            (salma, "submit", submit),
            (admin, "assign", {"officer": farhana.public_id}),
            (farhana, "start", {}),
            (farhana, "resolve", {"note": "Copy issued."}),
            (salma, "reopen", {"reason": "The copy is missing the second page."}),
        )
