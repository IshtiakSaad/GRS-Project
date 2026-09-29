"""Comments and attachments. Scope is the request's: whoever may see a request
may see its comments and files, except that citizens never see internal comments."""

import logging
import uuid

from django.db import transaction
from django.http import Http404
from django.utils.translation import gettext as _

from apps.accounts.models import Role, User
from apps.audit import services as audit
from apps.common import broker
from apps.common.errors import AppError
from apps.notifications import services as notifications
from apps.notifications.models import Kind
from apps.service_requests import transitions
from apps.service_requests.models import ServiceRequest, Status

from . import storage
from .models import Attachment, AttachmentStatus, Comment

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS_PER_REQUEST = 20
CLOSED = (Status.RESOLVED, Status.REJECTED, Status.WITHDRAWN)


def _locked(user: User, public_id) -> ServiceRequest:
    request = (
        transitions.visible_to(user)
        .select_for_update(of=("self",))
        .select_related("category")
        .filter(public_id=public_id)
        .first()
    )
    if request is None:
        raise Http404
    return request


def visible_request(user: User, public_id) -> ServiceRequest:
    request = transitions.visible_to(user).filter(public_id=public_id).first()
    if request is None:
        raise Http404
    return request


# --- comments ---------------------------------------------------------------------------------


def comments_for(user: User, request: ServiceRequest):
    rows = request.comments.select_related("author", "author__department")
    if user.role == Role.CITIZEN:
        rows = rows.filter(is_internal=False)
    return rows.order_by("created_at", "id")


def add_comment(
    user: User, public_id, body: str, *, internal: bool, respond: bool, http_request=None
) -> tuple[Comment, ServiceRequest]:
    """A citizen's comment while the office waits on them is their answer: unless they say
    otherwise it also resumes the request (the `respond` action), in the same transaction."""
    with transaction.atomic():
        request = _locked(user, public_id)
        if request.status == Status.DRAFT:
            raise AppError("NOT_SUBMITTED", _("Submit the request before commenting."), 409)
        citizen = user.role == Role.CITIZEN
        if internal and citizen:
            raise AppError("NOT_ALLOWED", _("Only staff can write internal comments."), 403)
        comment = Comment.objects.create(
            request=request, author=user, body=body, is_internal=internal
        )
        audit.record(
            "comment.create",
            actor=user,
            target=comment,
            request=request,
            data={"internal": internal},
            http_request=http_request,
        )
        if citizen and respond and request.status == Status.AWAITING_CITIZEN:
            transitions.apply(
                request, "respond", user, {"message": body}, http_request=http_request
            )
        elif not citizen and not internal:
            notifications.notify(
                request.owner,
                "request_comment",
                {"tracking_no": request.tracking_no},
                kind=Kind.STATUS,
                request=request,
                expires_in=transitions.STATUS_NOTICE_TTL,
            )
        return comment, request


# --- attachments ------------------------------------------------------------------------------


def visible_attachment(user: User, public_id) -> Attachment:
    attachment = (
        Attachment.objects.select_related("request", "uploaded_by")
        .filter(public_id=public_id, request__in=transitions.visible_to(user))
        .first()
    )
    if attachment is None:
        raise Http404
    return attachment


def start_upload(user: User, public_id, data: dict, http_request=None) -> Attachment:
    """Record the file and return it; the caller hands out the upload URL. Nothing is stored
    yet, and nothing is downloadable until the verifier has passed it."""
    with transaction.atomic():
        request = _locked(user, public_id)
        if request.status in CLOSED:
            raise AppError("REQUEST_CLOSED", _("This request is closed."), 409)
        if request.attachments.count() >= MAX_ATTACHMENTS_PER_REQUEST:
            raise AppError(
                "TOO_MANY_ATTACHMENTS", _("This request already has the most files allowed."), 409
            )
        attachment = Attachment.objects.create(
            request=request,
            uploaded_by=user,
            original_name=data["file_name"],
            declared_content_type=data["content_type"],
            declared_size=data["size"],
            # Our own name: the uploader's file name never becomes part of a storage path.
            storage_key=f"requests/{request.public_id}/{uuid.uuid4()}",
        )
        audit.record(
            "attachment.create",
            actor=user,
            target=attachment,
            request=request,
            data={"content_type": data["content_type"], "size": data["size"]},
            http_request=http_request,
        )
        return attachment


def confirm_upload(user: User, public_id, http_request=None) -> Attachment:
    """The uploader says the file is in place; verification starts. Repeating it is harmless."""
    from .tasks import verify_attachment

    with transaction.atomic():
        attachment = (
            Attachment.objects.select_for_update()
            .filter(public_id=public_id, uploaded_by=user)
            .select_related("request")
            .first()
        )
        if attachment is None:
            raise Http404
        if attachment.status == AttachmentStatus.REJECTED:
            raise AppError("ATTACHMENT_REJECTED", _("This file was rejected."), 409)
        if attachment.status == AttachmentStatus.PENDING:
            attachment.status = AttachmentStatus.VERIFYING
            attachment.save(update_fields=["status"])
            audit.record(
                "attachment.confirm",
                actor=user,
                target=attachment,
                request=attachment.request,
                http_request=http_request,
            )
            transaction.on_commit(lambda: _enqueue(verify_attachment, attachment.pk))
        return attachment


def _enqueue(task, pk: int) -> None:
    """A broker outage must not fail the upload: the stuck-verification sweep retries."""
    if not broker.enqueue(task, pk):
        logger.info("attachment %s left for the sweep", pk)


def download(user: User, attachment: Attachment) -> str:
    if attachment.status != AttachmentStatus.READY:
        raise AppError("ATTACHMENT_NOT_READY", _("This file is not available."), 409)
    return storage.download_url(
        attachment.storage_key, attachment.original_name, attachment.detected_content_type
    )
