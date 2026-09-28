"""History cannot be rewritten, even by the table owner.

These run as grs_owner, which has full table rights: only the triggers stand in the way. The
role tests show the second, independent layer (missing grants).
"""

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.audit.models import GENESIS_HASH, AccessEvent, AccessEventItem, AuditAnchor, AuditLog
from apps.service_requests.models import RequestEvent
from tests import factories as f

pytestmark = pytest.mark.django_db


def _refused(queryset_action, match="append-only|immutable|only be updated|may not change"):
    with pytest.raises(DatabaseError, match=match), transaction.atomic():
        queryset_action()


def test_request_events_cannot_change():
    request = f.submitted()
    event = RequestEvent.objects.create(request=request, event_type="SUBMITTED")
    _refused(lambda: RequestEvent.objects.filter(pk=event.pk).update(event_type="FORGED"))
    _refused(lambda: RequestEvent.objects.filter(pk=event.pk).delete())


def test_access_events_and_items_cannot_change():
    request = f.submitted()
    staff = f.officer()
    event = AccessEvent.objects.create(
        actor=staff, actor_role=staff.role, kind="LIST", item_count=1
    )
    AccessEventItem.objects.create(event_id=event.pk, request=request, created_at=event.created_at)
    _refused(lambda: AccessEvent.objects.filter(pk=event.pk).update(kind="VIEW"))
    _refused(lambda: AccessEvent.objects.filter(pk=event.pk).delete())
    _refused(lambda: AccessEventItem.objects.filter(event_id=event.pk).delete())


def _seal(**extra):
    return {
        "seal_seq": 1,
        "prev_hash": GENESIS_HASH,
        "row_hash": "a" * 64,
        "sealed_at": timezone.now(),
        **extra,
    }


def test_audit_row_can_be_sealed_exactly_once():
    row = AuditLog.objects.create(action="request.submit", target_type="request", target_id=1)
    AuditLog.objects.filter(pk=row.pk).update(**_seal())
    _refused(lambda: AuditLog.objects.filter(pk=row.pk).update(**_seal(row_hash="b" * 64)))


def test_sealing_cannot_alter_content():
    row = AuditLog.objects.create(action="request.submit", target_type="request", target_id=1)
    _refused(lambda: AuditLog.objects.filter(pk=row.pk).update(**_seal(action="request.forged")))


def test_unsealed_audit_row_cannot_be_edited_or_deleted():
    row = AuditLog.objects.create(action="request.submit", target_type="request", target_id=1)
    _refused(lambda: AuditLog.objects.filter(pk=row.pk).update(action="request.forged"))
    _refused(lambda: AuditLog.objects.filter(pk=row.pk).delete())


def test_anchor_receipt_is_recorded_once():
    anchor = AuditAnchor.objects.create(
        first_seal_seq=1, last_seal_seq=100, last_row_hash="a" * 64, object_key="anchors/1"
    )
    AuditAnchor.objects.filter(pk=anchor.pk).update(stored_at=timezone.now(), object_version="v1")
    _refused(lambda: AuditAnchor.objects.filter(pk=anchor.pk).update(object_version="v2"))
    _refused(lambda: AuditAnchor.objects.filter(pk=anchor.pk).delete())


def test_anchor_content_cannot_change_before_storage():
    anchor = AuditAnchor.objects.create(
        first_seal_seq=1, last_seal_seq=100, last_row_hash="a" * 64, object_key="anchors/2"
    )
    _refused(lambda: AuditAnchor.objects.filter(pk=anchor.pk).update(last_row_hash="b" * 64))
