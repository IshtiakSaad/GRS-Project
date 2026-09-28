"""Every rule the database enforces, proven by trying to break it.

Each case writes one illegal row straight through the ORM, with no serializer or service in the
way, and expects PostgreSQL itself to refuse it. If a future change drops a constraint, the
matching case fails.
"""

from datetime import date, timedelta

import pytest
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import OtpChallenge, RefreshSession, Role, User
from apps.audit.models import AccessAlert, AccessEvent, AuditAnchor, AuditLog
from apps.collab.models import Attachment, Comment
from apps.common.ids import uuid7
from apps.directory.models import Category, SlaSuspension
from apps.notifications.models import Notification
from apps.service_requests.models import ServiceRequest, SlaPause, Status
from tests import factories as f

pytestmark = pytest.mark.django_db

NOW = timezone.now()


def _user(**kw):
    return User.objects.create(**{"phone": f.phone(), "full_name": "X", **kw})


def _request_update(**changes):
    request = f.submitted()
    ServiceRequest.objects.filter(pk=request.pk).update(**changes)


def _attachment(**kw):
    request = f.draft()
    Attachment.objects.create(
        **{
            "request": request,
            "uploaded_by": request.owner,
            "original_name": "id.jpg",
            "declared_content_type": "image/jpeg",
            "declared_size": 1000,
            "storage_key": f"k/{uuid7()}",
            **kw,
        }
    )


def _notification(**kw):
    Notification.objects.create(
        **{
            "recipient": f.citizen(),
            "channel": "SMS",
            "kind": "STATUS",
            "template": "status_changed",
            **kw,
        }
    )


def _access_event(**kw):
    staff = f.officer()
    AccessEvent.objects.create(**{"actor": staff, "actor_role": staff.role, "kind": "VIEW", **kw})


def _alert(**kw):
    staff = f.officer()
    AccessAlert.objects.create(
        **{
            "actor": staff,
            "rule": "BULK_VIEW",
            "window_start": NOW,
            "window_end": NOW + timedelta(hours=1),
            "observed": 900,
            "threshold": 200,
            **kw,
        }
    )


ILLEGAL = {
    # accounts
    "phone not E.164 Bangladeshi": lambda: _user(phone="01712345678"),
    "phone foreign": lambda: _user(phone="+447700900123"),
    "unknown role": lambda: _user(role="SUPERUSER"),
    "unknown language": lambda: _user(preferred_language="fr"),
    "officer without department": lambda: _user(role=Role.OFFICER),
    "active admin without TOTP": lambda: _user(role=Role.ADMIN),
    "duplicate email ignoring case": lambda: (
        _user(email="a@example.com"),
        _user(email="A@Example.com"),
    ),
    "duplicate phone": lambda: (_user(phone="+8801000000001"), _user(phone="+8801000000001")),
    "OTP over five attempts": lambda: OtpChallenge.objects.create(
        phone=f.phone(),
        purpose="VERIFY_PHONE",
        code_hmac="x",
        attempts=6,
        expires_at=NOW + timedelta(minutes=10),
    ),
    "OTP expiring before creation": lambda: OtpChallenge.objects.create(
        phone=f.phone(), purpose="VERIFY_PHONE", code_hmac="x", expires_at=NOW - timedelta(days=1)
    ),
    "session idle expiry beyond absolute": lambda: RefreshSession.objects.create(
        user=f.citizen(),
        family_id=uuid7(),
        trust_mode="SHARED",
        token_hash="h" * 64,
        idle_expires_at=NOW + timedelta(days=2),
        absolute_expires_at=NOW + timedelta(days=1),
    ),
    # directory
    "category with zero target days": lambda: f.category(target_working_days=0),
    "suspension ending before it starts": lambda: SlaSuspension.objects.create(
        starts_on=date(2026, 8, 5), ends_on=date(2026, 8, 1), reason="x", created_by=f.admin()
    ),
    # requests
    "unknown status": lambda: _request_update(status="CLOSED"),
    "priority out of range": lambda: _request_update(priority=9),
    "tracking number malformed": lambda: _request_update(tracking_no="2026-42"),
    "submitted without tracking number": lambda: _request_update(tracking_no=None),
    "submitted without deadline": lambda: _request_update(due_at=None),
    "assigned without officer": lambda: _request_update(status=Status.ASSIGNED),
    "resolved without note": lambda: _request_update(
        status=Status.RESOLVED, assigned_officer=f.officer(), resolved_at=NOW
    ),
    "rejected without reason": lambda: _request_update(status=Status.REJECTED),
    "urgent without reason": lambda: _request_update(citizen_urgent=True),
    "assisted by the owner": lambda: _request_update(assisted=True),
    "beneficiary name without relation": lambda: _request_update(beneficiary_name="Ayesha"),
    "fourth information request": lambda: _request_update(info_request_count=4),
    "third reopen": lambda: _request_update(reopen_count=3),
    "deadline before submission": lambda: _request_update(due_at=NOW - timedelta(days=30)),
    "title over 200 characters": lambda: f.draft(title="x" * 201),
    "two open SLA pauses": lambda: (
        (r := f.submitted()),
        SlaPause.objects.create(request=r, reason_code="MISSING_DOCUMENT", started_at=NOW),
        SlaPause.objects.create(request=r, reason_code="MISSING_DOCUMENT", started_at=NOW),
    ),
    "pause ending before it starts": lambda: SlaPause.objects.create(
        request=f.submitted(),
        reason_code="OTHER",
        started_at=NOW,
        ended_at=NOW - timedelta(hours=1),
    ),
    # collaboration
    "empty comment": lambda: Comment.objects.create(
        request=(r := f.draft()), author=r.owner, body=""
    ),
    "attachment over 10 MB": lambda: _attachment(declared_size=11 * 1024 * 1024),
    "attachment ready without verification": lambda: _attachment(status="READY"),
    "attachment rejected without reason": lambda: _attachment(status="REJECTED"),
    "attachment hash malformed": lambda: _attachment(sha256="not-a-hash"),
    # notifications
    "unknown channel": lambda: _notification(channel="FAX"),
    "action-required that expires": lambda: _notification(
        kind="ACTION_REQUIRED", expires_at=NOW + timedelta(days=3)
    ),
    "leased without lease token": lambda: _notification(status="LEASED"),
    "too many attempts": lambda: _notification(attempts=9),
    # audit
    "audit half-sealed": lambda: AuditLog.objects.create(
        action="x", target_type="t", row_hash="a" * 64
    ),
    "anchor with inverted range": lambda: AuditAnchor.objects.create(
        first_seal_seq=10, last_seal_seq=5, last_row_hash="a" * 64, object_key="k1"
    ),
    "view event without a request": lambda: _access_event(),
    "break-glass OTHER without explanation": lambda: _access_event(
        request=f.submitted(), break_glass_reason="OTHER", break_glass_note="because"
    ),
    "alert reviewed by the person flagged": lambda: (
        (a := f.officer()),
        _alert(actor=a, status="ACKNOWLEDGED", reviewed_by=a, reviewed_at=NOW),
    ),
    "alert closed without reviewer": lambda: _alert(status="DISMISSED"),
}


@pytest.mark.parametrize("build", ILLEGAL.values(), ids=ILLEGAL.keys())
def test_database_refuses(build):
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        build()


def test_valid_rows_are_accepted():
    """The baseline each illegal case departs from must itself be legal."""
    f.admin()
    request = f.submitted(beneficiary_name="Ayesha", beneficiary_relation="CHILD")
    Comment.objects.create(request=request, author=request.owner, body="Thank you")
    _attachment()
    _notification(kind="ACTION_REQUIRED")
    _access_event(request=request, break_glass_reason="OTHER", break_glass_note="x" * 20)
    _alert()


def test_category_cannot_change_department():
    category = f.category()
    with pytest.raises(IntegrityError, match="cannot change department"), transaction.atomic():
        Category.objects.filter(pk=category.pk).update(department=f.department())
    Category.objects.filter(pk=category.pk).update(name_en="Renamed")  # other edits are fine
