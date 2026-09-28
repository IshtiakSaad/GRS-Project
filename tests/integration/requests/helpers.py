"""A cast of users around one department, and requests put straight into any state."""

import itertools
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.directory.models import Category
from apps.service_requests.models import ServiceRequest, SlaPause, Status
from tests import factories

_keys = itertools.count(1)


@dataclass
class Cast:
    category: Category
    owner: User
    stranger: User  # another citizen
    assigned: User  # the officer a request is assigned to
    colleague: User  # another officer of the same department
    outsider: User  # an officer of another department
    admin: User

    def by_name(self, name: str) -> User:
        return getattr(self, name)


def cast() -> Cast:
    category = factories.category()
    dept = category.department
    return Cast(
        category=category,
        owner=factories.citizen(phone_verified_at=timezone.now()),
        stranger=factories.citizen(phone_verified_at=timezone.now()),
        assigned=factories.officer(dept),
        colleague=factories.officer(dept),
        outsider=factories.officer(),
        admin=factories.admin(),
    )


def in_state(c: Cast, status: str) -> ServiceRequest:
    """A request of c.owner in `status`, with the columns that state requires."""
    if status == Status.DRAFT:
        return factories.draft(owner=c.owner, cat=c.category)
    now = timezone.now()
    # Filed two days ago: PostgreSQL's now() inside a test is the start of the test's
    # transaction, which must not fall before the submission.
    filed = now - timedelta(days=2)
    extra = {"submitted_at": filed, "sla_started_at": filed}
    if status in (Status.ASSIGNED, Status.IN_PROGRESS, Status.AWAITING_CITIZEN):
        extra["assigned_officer"] = c.assigned
    if status == Status.RESOLVED:
        extra |= {"assigned_officer": c.assigned, "resolution_note": "Done.", "resolved_at": now}
    if status == Status.REJECTED:
        extra |= {"assigned_officer": c.assigned, "rejection_reason_code": "OTHER"}
    if status in (Status.RESOLVED, Status.REJECTED):
        extra |= {"closed_at": now, "reopen_deadline": now + timedelta(days=30)}
    if status == Status.WITHDRAWN:
        extra["closed_at"] = now
    request = factories.submitted(owner=c.owner, cat=c.category, status=status, **extra)
    if status == Status.AWAITING_CITIZEN:
        SlaPause.objects.create(
            request=request, reason_code="OTHER", started_at=now - timedelta(hours=1)
        )
    return request


def key() -> str:
    return f"test-key-{next(_keys):06d}"


def act(api, request: ServiceRequest, action: str, body: dict | None = None, **headers):
    if action == "submit":
        headers.setdefault("HTTP_IDEMPOTENCY_KEY", key())
    return api.post(
        f"/api/v1/requests/{request.public_id}/actions/{action}",
        body or {},
        format="json",
        **headers,
    )


def draft_body(cat: Category, **extra) -> dict:
    return {
        "category": cat.code,
        "title": "Birth certificate correction",
        "description": "My name is misspelled on the certificate.",
        **extra,
    }
