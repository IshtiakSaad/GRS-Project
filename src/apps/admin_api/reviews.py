"""The review queue: closed requests an administrator checks after the fact.

Late rejections are always queued (rejecting near the deadline is a way to dodge the SLA);
a random share of resolutions is too, so quality is checked, not assumed. Upholding closes
the review. Overturning sends the request back to the queue with a new SLA cycle.
"""

from django.db import transaction
from django.db.models.functions import Now
from django.http import Http404
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.common.errors import AppError
from apps.service_requests import transitions
from apps.service_requests.models import Review, ReviewStatus, ServiceRequest

UPHOLD, OVERTURN = "UPHOLD", "OVERTURN"


def queue(*, status=None, reason=None, department=None):
    rows = Review.objects.select_related(
        "request", "request__department", "request__category", "officer", "reviewer"
    )
    if status:
        rows = rows.filter(status=status)
    if reason:
        rows = rows.filter(reason=reason)
    if department:
        rows = rows.filter(request__department__code=department)
    return rows


def decide(admin: User, public_id, decision: str, note: str | None, http_request=None) -> Review:
    with transaction.atomic():
        review = Review.objects.select_for_update().filter(public_id=public_id).first()
        if review is None:
            raise Http404
        if review.status != ReviewStatus.PENDING:
            raise AppError("ALREADY_REVIEWED", _("This review has already been decided."), 409)
        if review.officer_id == admin.pk:
            raise AppError("OWN_DECISION", _("You cannot review your own decision."), 403)

        if decision == OVERTURN:
            request = (
                ServiceRequest.objects.select_for_update(of=("self",))
                .select_related("category")
                .get(pk=review.request_id)
            )
            if request.status != review.decided_status:
                # The citizen reopened it, or another review already sent it back.
                raise AppError(
                    "REQUEST_CHANGED",
                    _("The request has changed since this decision; uphold or look again."),
                    409,
                )
            transitions.apply(
                request, "overturn", admin, {"reason": note}, http_request=http_request
            )

        review.status = ReviewStatus.OVERTURNED if decision == OVERTURN else ReviewStatus.UPHELD
        review.reviewer = admin
        review.note = note or None
        review.reviewed_at = Now()
        review.save(update_fields=["status", "reviewer", "note", "reviewed_at"])
        audit.record(
            "review.decide",
            actor=admin,
            target=review,
            request=review.request,
            data={"decision": review.status, "reason": review.reason},
            http_request=http_request,
        )
    review.refresh_from_db()
    return review
