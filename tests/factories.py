"""Minimal valid rows. Tests change one thing at a time from these and expect a refusal."""

import itertools
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import Role, User
from apps.directory.models import Category, Department
from apps.service_requests.models import ServiceRequest, Status

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


def phone() -> str:
    return f"+88010{_n():08d}"  # 010: unassigned prefix, never a real subscriber


def department(**kw) -> Department:
    n = _n()
    return Department.objects.create(
        **{"code": f"D{n}", "name_bn": f"বিভাগ {n}", "name_en": f"Dept {n}", **kw}
    )


def category(dept=None, **kw) -> Category:
    n = _n()
    return Category.objects.create(
        **{
            "department": dept or department(),
            "code": f"C{n}",
            "name_bn": f"সেবা {n}",
            "name_en": f"Service {n}",
            "target_working_days": 7,
            **kw,
        }
    )


def citizen(**kw) -> User:
    return User.objects.create_user(phone(), "pw", **{"full_name": "Rahim Uddin", **kw})


def officer(dept=None, **kw) -> User:
    return User.objects.create_user(
        phone(),
        "pw",
        **{
            "full_name": "Karim Officer",
            "role": Role.OFFICER,
            "department": dept or department(),
            **kw,
        },
    )


def admin(**kw) -> User:
    return User.objects.create_user(
        phone(),
        "pw",
        **{"full_name": "Admin", "role": Role.ADMIN, "totp_enabled_at": timezone.now(), **kw},
    )


def draft(owner=None, cat=None, **kw) -> ServiceRequest:
    owner = owner or citizen()
    cat = cat or category()
    return ServiceRequest.objects.create(
        **{
            "owner": owner,
            "submitted_by": owner,
            "category": cat,
            "department": cat.department,
            "title": "Birth certificate correction",
            "description": "My name is misspelled.",
            **kw,
        }
    )


def submitted(**kw) -> ServiceRequest:
    now = timezone.now()
    return draft(
        **{
            "status": Status.SUBMITTED,
            "tracking_no": f"26-{_n():07d}-0",
            "submitted_at": now,
            "due_at": now + timedelta(days=7),
            **kw,
        }
    )
