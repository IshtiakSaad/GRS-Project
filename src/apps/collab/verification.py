"""Verify one uploaded file (design §13.2). Runs in the worker, never in a web request.

Checks, in order: something was uploaded; its real size is the declared size; its first bytes
are an allowed type and the declared one; the scanner finds nothing. Only then READY. A file
that fails is REJECTED and deleted from the store: it can never be downloaded.
"""

import hashlib
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models.functions import Now

from apps.audit import services as audit

from . import storage
from .models import MAX_ATTACHMENT_BYTES, Attachment, AttachmentStatus
from .scanning import SNIFF_BYTES, detect_type, new_scanner

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=10)


class Rejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _inspect(attachment: Attachment) -> dict:
    size = storage.size_of(attachment.storage_key)
    if size is None:
        raise Rejected("NOT_UPLOADED")
    if size != attachment.declared_size or size > MAX_ATTACHMENT_BYTES:
        raise Rejected("SIZE_MISMATCH")

    digest, scanner, head, total = hashlib.sha256(), new_scanner(), b"", 0
    for chunk in storage.chunks(attachment.storage_key):
        total += len(chunk)
        if total > MAX_ATTACHMENT_BYTES:
            raise Rejected("SIZE_MISMATCH")  # changed since the size check
        if len(head) < SNIFF_BYTES:
            head += chunk[: SNIFF_BYTES - len(head)]
        digest.update(chunk)
        scanner.feed(chunk)

    detected = detect_type(head)
    if detected is None or detected != attachment.declared_content_type:
        raise Rejected("TYPE_MISMATCH")
    threat = scanner.verdict()
    if threat is not None:
        logger.warning("attachment %s rejected by scanner: %s", attachment.pk, threat)
        raise Rejected("MALWARE")
    return {"size_bytes": total, "sha256": digest.hexdigest(), "detected_content_type": detected}


def verify(attachment_id: int) -> str:
    """Returns the resulting status, or "skipped" if the file is not waiting for verification.
    Storage errors propagate, so the task retries; the file stays VERIFYING meanwhile."""
    attachment = Attachment.objects.filter(
        pk=attachment_id, status=AttachmentStatus.VERIFYING
    ).first()
    if attachment is None:
        return "skipped"
    try:
        found = _inspect(attachment)
    except Rejected as rejected:
        return _finish(attachment, AttachmentStatus.REJECTED, rejection_reason=rejected.reason)
    return _finish(attachment, AttachmentStatus.READY, **found)


def _finish(attachment: Attachment, status: str, **fields) -> str:
    with transaction.atomic():
        # Conditional: of two workers verifying one file, only one records the result.
        updated = Attachment.objects.filter(
            pk=attachment.pk, status=AttachmentStatus.VERIFYING
        ).update(status=status, verified_at=Now(), **fields)
        if not updated:
            return "skipped"
        request = attachment.request
        audit.record(
            f"attachment.{status.lower()}",
            target=attachment,
            request=request,
            data={"reason": fields.get("rejection_reason")}
            if fields.get("rejection_reason")
            else {"sha256": fields["sha256"]},
        )
        if status == AttachmentStatus.READY:
            request.events.create(
                actor=attachment.uploaded_by,
                actor_role=attachment.uploaded_by.role,
                event_type="attachment_added",
                is_public=True,
                data={"attachment": str(attachment.public_id), "name": attachment.original_name},
            )
    if status == AttachmentStatus.REJECTED:
        try:
            storage.delete(attachment.storage_key)
        except Exception:  # noqa: BLE001 - never downloadable anyway; cleanup can retry later
            logger.warning("could not delete rejected attachment %s", attachment.pk)
    return status


def stuck() -> list[int]:
    """Files confirmed long ago whose verification never finished (a lost task, a worker crash,
    storage down): the sweep hands them back to the verifier."""
    return list(
        Attachment.objects.filter(
            status=AttachmentStatus.VERIFYING, created_at__lt=Now() - STUCK_AFTER
        ).values_list("pk", flat=True)[:500]
    )
