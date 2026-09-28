"""Drafts, the queue and lookups. State changes of submitted requests live in transitions.py."""

from django.db import transaction
from django.http import Http404
from django.utils.translation import gettext as _

from apps.accounts.models import Role, User
from apps.common.errors import AppError
from apps.directory.models import Category

from . import tracking, transitions
from .models import ServiceRequest, Status

MAX_OPEN_DRAFTS = 20  # drafts are free to create; this keeps one account from filling a table


def active_category(code: str) -> Category:
    category = (
        Category.objects.select_related("department")
        .filter(code=code, is_active=True, department__is_active=True)
        .first()
    )
    if category is None:
        message = _("Choose a service from the list.")
        raise AppError("INVALID_CATEGORY", message, 400, fields={"category": [message]})
    return category


def _fields(data: dict) -> dict:
    beneficiary = data.get("beneficiary")
    if data.get("citizen_urgent") and not data.get("urgency_reason"):
        message = _("Say why the request is urgent.")
        raise AppError("VALIDATION_ERROR", message, 400, fields={"urgency_reason": [message]})
    return {
        "title": data["title"],
        "description": data["description"],
        "beneficiary_name": beneficiary["name"] if beneficiary else None,
        "beneficiary_relation": beneficiary["relation"] if beneficiary else None,
        "citizen_urgent": data.get("citizen_urgent", False),
        "urgency_reason": data.get("urgency_reason") if data.get("citizen_urgent") else None,
    }


def create_draft(owner: User, data: dict) -> ServiceRequest:
    if ServiceRequest.objects.filter(owner=owner, status=Status.DRAFT).count() >= MAX_OPEN_DRAFTS:
        raise AppError("TOO_MANY_DRAFTS", _("Submit or delete some of your drafts first."), 409)
    category = active_category(data["category"])
    return ServiceRequest.objects.create(
        owner=owner,
        submitted_by=owner,
        category=category,
        department=category.department,
        **_fields(data),
    )


def _locked_draft(owner: User, public_id, if_match: int | None) -> ServiceRequest:
    draft = (
        ServiceRequest.objects.select_for_update().filter(owner=owner, public_id=public_id).first()
    )
    if draft is None:
        raise Http404
    if draft.status != Status.DRAFT:
        raise AppError(
            "NOT_A_DRAFT", _("A submitted request can no longer be edited or deleted."), 409
        )
    transitions.check_version(draft, if_match)
    return draft


def edit_draft(owner: User, public_id, data: dict, if_match: int) -> ServiceRequest:
    with transaction.atomic():
        draft = _locked_draft(owner, public_id, if_match)
        if "category" in data:
            category = active_category(data["category"])
            draft.category, draft.department = category, category.department
        current = {
            "title": draft.title,
            "description": draft.description,
            "beneficiary": draft.beneficiary_name
            and {"name": draft.beneficiary_name, "relation": draft.beneficiary_relation},
            "citizen_urgent": draft.citizen_urgent,
            "urgency_reason": draft.urgency_reason,
        }
        for name, value in _fields(current | data).items():
            setattr(draft, name, value)
        draft.version += 1
        draft.save()
        return draft


def discard_draft(owner: User, public_id, if_match: int | None) -> None:
    with transaction.atomic():
        _locked_draft(owner, public_id, if_match).delete()


def claim_next(officer: User, http_request=None) -> ServiceRequest | None:
    """The officer's department's most urgent waiting request, or None if the queue is empty.

    SKIP LOCKED: officers claiming at the same moment each get a different request, and nobody
    waits for anybody else's transaction. Officers cannot choose which request they take.
    """
    with transaction.atomic():
        request = (
            queue(officer)
            .select_for_update(skip_locked=True, of=("self",))
            .select_related("category")
            .first()
        )
        if request is None:
            return None
        return transitions.apply(request, "claim_next", officer, {}, http_request=http_request)


def queue(officer: User):
    """Design §5.4: priority, then earliest deadline, then first come. Served by
    sr_dept_queue_idx."""
    if officer.role != Role.OFFICER:
        return ServiceRequest.objects.none()
    return ServiceRequest.objects.filter(
        department_id=officer.department_id, status=Status.SUBMITTED
    ).order_by("-priority", "due_at", "submitted_at", "id")


def _tracking_no(raw: str) -> str:
    number = tracking.parse_tracking_no(raw)
    if number is None:
        raise AppError(
            "INVALID_TRACKING_NO",
            _("This tracking number is not valid. Check it and try again."),
            400,
        )
    return number


def by_tracking_no(user: User, raw: str) -> ServiceRequest:
    request = transitions.visible_to(user).filter(tracking_no=_tracking_no(raw)).first()
    if request is None:
        raise Http404
    return request


def by_tracking_no_anywhere(raw: str) -> ServiceRequest:
    """For break-glass only: any submitted request, whatever the caller's scope."""
    request = ServiceRequest.objects.filter(tracking_no=_tracking_no(raw)).first()
    if request is None:  # drafts have no tracking number, so they are never found
        raise Http404
    return request
