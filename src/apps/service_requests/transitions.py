"""The only way a submitted request changes (design §5.2, rule R3).

One transaction per change: lock the row → check who and from which state → change it →
timeline event → audit row → notifications. The rules are data (RULES); each action's own
work is a small function (HANDLERS). Tests walk every (state, action, actor) cell of the table.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from django.db import connection, transaction
from django.db.models import Q
from django.http import Http404
from django.utils.translation import gettext as _

from apps.accounts.models import Role, User
from apps.audit import services as audit
from apps.common.errors import AppError
from apps.notifications import services as notifications
from apps.notifications.models import Kind
from apps.sla.services import compute_due_at

from . import tracking
from .models import OPEN_STATUSES, ServiceRequest, SlaPause, Status

REOPEN_WINDOW = timedelta(days=30)
MAX_INFO_REQUESTS = 2  # the database allows a third, for when an administrator approves one
MAX_REOPENS = 2
DUPLICATE_WINDOW = timedelta(minutes=10)
STATUS_NOTICE_TTL = timedelta(hours=72)
LATE_REJECTION_SHARE = 0.8  # rejections in the last 20% of the SLA window are sampled


class Actor(StrEnum):
    OWNER = "OWNER"
    ASSIGNED = "ASSIGNED"  # the officer the request is assigned to
    DEPARTMENT = "DEPARTMENT"  # any officer of the request's department
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class Rule:
    sources: frozenset[str]
    target: str | None  # None: the status does not change
    actors: frozenset[Actor]
    public: bool = True  # shown on the citizen's timeline


def _rule(sources, target, *actors, public=True) -> Rule:
    return Rule(frozenset(sources), target, frozenset(actors), public)


S = Status
RULES: dict[str, Rule] = {
    "submit": _rule([S.DRAFT], S.SUBMITTED, Actor.OWNER),
    "claim_next": _rule([S.SUBMITTED], S.ASSIGNED, Actor.DEPARTMENT),
    "assign": _rule([S.SUBMITTED], S.ASSIGNED, Actor.ADMIN),
    "reassign": _rule([S.ASSIGNED, S.IN_PROGRESS], None, Actor.ADMIN, public=False),
    "start": _rule([S.ASSIGNED], S.IN_PROGRESS, Actor.ASSIGNED),
    "request_info": _rule([S.IN_PROGRESS], S.AWAITING_CITIZEN, Actor.ASSIGNED),
    "respond": _rule([S.AWAITING_CITIZEN], S.IN_PROGRESS, Actor.OWNER),
    "resume": _rule([S.AWAITING_CITIZEN], S.IN_PROGRESS, Actor.ASSIGNED),
    "resolve": _rule([S.IN_PROGRESS], S.RESOLVED, Actor.ASSIGNED),
    "reject": _rule(OPEN_STATUSES, S.REJECTED, Actor.ASSIGNED, Actor.ADMIN),
    "withdraw": _rule(OPEN_STATUSES, S.WITHDRAWN, Actor.OWNER),
    "reopen": _rule([S.RESOLVED, S.REJECTED], S.SUBMITTED, Actor.OWNER),
    "set_priority": _rule(
        OPEN_STATUSES, None, Actor.ASSIGNED, Actor.DEPARTMENT, Actor.ADMIN, public=False
    ),
}


def actors_of(user: User, request: ServiceRequest) -> set[Actor]:
    found = set()
    if request.owner_id == user.pk:
        found.add(Actor.OWNER)
    if user.role == Role.OFFICER:
        if request.assigned_officer_id == user.pk:
            found.add(Actor.ASSIGNED)
        if request.department_id == user.department_id:
            found.add(Actor.DEPARTMENT)
    if user.role == Role.ADMIN:
        found.add(Actor.ADMIN)
    return found


def visible_to(user: User):
    """Requests a user may see (design §7.5). Anything else is answered with 404, so staff
    cannot learn that a request exists outside their scope. Drafts are the owner's alone."""
    requests = ServiceRequest.objects.all()
    if user.role == Role.CITIZEN:
        return requests.filter(owner=user)
    requests = requests.exclude(status=Status.DRAFT)
    if user.role == Role.OFFICER:
        return requests.filter(Q(department_id=user.department_id) | Q(assigned_officer=user))
    if user.role == Role.ADMIN:
        return requests
    return requests.none()


# --- what an action does ----------------------------------------------------------------------


@dataclass
class Change:
    event: dict = field(default_factory=dict)  # timeline data; citizens may see it
    audit: dict = field(default_factory=dict)  # extra detail for auditors only
    notices: list[tuple[User, str, str]] = field(default_factory=list)  # recipient, template, kind


@dataclass
class Context:
    user: User
    now: object  # the transaction's timestamp from PostgreSQL
    data: dict


def _refuse(code: str, message: str, status: int = 409) -> AppError:
    return AppError(code, message, status)


def _content_hash(request: ServiceRequest) -> str:
    text = f"{request.category_id}\n{request.title}\n{request.description}"
    return hashlib.sha256(text.encode()).hexdigest()


def _submit(request: ServiceRequest, ctx: Context) -> Change:
    owner = User.objects.select_for_update().get(pk=request.owner_id)  # serialises the check
    if owner.phone_verified_at is None and (
        ServiceRequest.objects.filter(owner=owner).exclude(status=Status.DRAFT).exists()
    ):
        raise _refuse(
            "PHONE_NOT_VERIFIED",
            _("Verify your phone number to submit more than one request."),
            403,
        )
    category = request.category
    if not (category.is_active and category.department.is_active):
        raise _refuse("CATEGORY_INACTIVE", _("This service is no longer offered."))

    request.content_hash = _content_hash(request)
    if not ctx.data.get("confirm_duplicate"):
        earlier = (
            ServiceRequest.objects.filter(
                owner=owner,
                content_hash=request.content_hash,
                submitted_at__gte=ctx.now - DUPLICATE_WINDOW,
            )
            .exclude(pk=request.pk)
            .values_list("tracking_no", flat=True)
            .first()
        )
        if earlier:
            raise AppError(
                "POSSIBLE_DUPLICATE",
                _("You submitted the same request a few minutes ago."),
                409,
                fields={"tracking_no": earlier},
            )

    with connection.cursor() as cursor:  # after every refusal: a refused submit wastes no number
        cursor.execute("SELECT y, next_tracking_serial(y) FROM tracking_year(%s) AS y", [ctx.now])
        year, serial = cursor.fetchone()
    request.tracking_no = tracking.format_tracking_no(year, serial)
    request.submitted_at = request.sla_started_at = ctx.now
    request.due_at = compute_due_at(request)
    return Change(
        event={"tracking_no": request.tracking_no},
        notices=[(owner, "request_submitted", Kind.STATUS)],
    )


def _officer_from(ctx: Context, request: ServiceRequest) -> User:
    officer = User.objects.filter(
        public_id=ctx.data["officer"],
        role=Role.OFFICER,
        is_active=True,
        department_id=request.department_id,
    ).first()
    if officer is None:
        raise AppError(
            "INVALID_OFFICER",
            _("Choose an active officer of this request's department."),
            400,
            fields={"officer": [_("Choose an active officer of this request's department.")]},
        )
    return officer


def _claim_next(request, ctx):
    request.assigned_officer = ctx.user
    return Change()


def _assign(request, ctx):
    officer = _officer_from(ctx, request)
    request.assigned_officer = officer
    return Change(
        audit={"officer": str(officer.public_id)},
        notices=[(officer, "request_assigned", Kind.STATUS)],
    )


def _reassign(request, ctx):
    officer = _officer_from(ctx, request)
    if officer.pk == request.assigned_officer_id:
        raise _refuse("SAME_OFFICER", _("The request is already assigned to this officer."))
    previous = request.assigned_officer
    request.assigned_officer = officer
    request.reassignment_count += 1
    return Change(
        event={"reason": ctx.data["reason"]},
        audit={"from_officer": str(previous.public_id), "officer": str(officer.public_id)},
        notices=[(officer, "request_assigned", Kind.STATUS)],
    )


def _start(request, ctx):
    return Change(notices=[(request.owner, "request_started", Kind.STATUS)])


def _request_info(request, ctx):
    if request.info_request_count >= MAX_INFO_REQUESTS:
        raise _refuse(
            "INFO_REQUEST_LIMIT",
            _("Information was already requested twice. An administrator must review this."),
        )
    request.info_request_count += 1
    SlaPause.objects.create(
        request=request, reason_code=ctx.data["reason_code"], started_at=ctx.now
    )
    return Change(
        event={"reason_code": ctx.data["reason_code"], "message": ctx.data["message"]},
        notices=[(request.owner, "request_info_needed", Kind.ACTION_REQUIRED)],
    )


def _respond(request, ctx):
    return Change(event={"message": ctx.data["message"]})


def _resume(request, ctx):
    return Change(event={"reason": ctx.data["reason"]})


def _resolve(request, ctx):
    request.resolution_note = ctx.data["note"]
    request.resolved_at = request.closed_at = ctx.now
    request.reopen_deadline = ctx.now + REOPEN_WINDOW
    return Change(
        event={"note": request.resolution_note},
        notices=[(request.owner, "request_resolved", Kind.STATUS)],
    )


def _reject(request, ctx):
    request.rejection_reason_code = ctx.data["reason_code"]
    request.rejection_note = ctx.data["note"]
    request.closed_at = ctx.now
    request.reopen_deadline = ctx.now + REOPEN_WINDOW
    window = request.due_at - request.sla_started_at
    late = ctx.now >= request.sla_started_at + window * LATE_REJECTION_SHARE
    return Change(
        event={"reason_code": request.rejection_reason_code, "note": request.rejection_note},
        audit={"late_rejection": late},
        notices=[(request.owner, "request_rejected", Kind.STATUS)],
    )


def _withdraw(request, ctx):
    request.closed_at = ctx.now
    officer = request.assigned_officer
    notices = [(officer, "request_withdrawn", Kind.STATUS)] if officer else []
    return Change(event={"reason": ctx.data.get("reason") or ""}, notices=notices)


def _reopen(request, ctx):
    if request.reopen_count >= MAX_REOPENS:
        raise _refuse("REOPEN_LIMIT", _("This request cannot be reopened again."))
    if request.reopen_deadline is None or ctx.now > request.reopen_deadline:
        raise _refuse("REOPEN_WINDOW_CLOSED", _("The time to reopen this request has passed."))
    request.reopen_count += 1
    request.assigned_officer = None
    request.resolution_note = request.resolved_at = None
    request.rejection_reason_code = request.rejection_note = None
    request.closed_at = request.reopen_deadline = None
    request.sla_started_at = ctx.now  # a new cycle and a new deadline
    request.due_at = compute_due_at(request)
    return Change(event={"reason": ctx.data["reason"]})


def _set_priority(request, ctx):
    before = request.priority
    request.priority = ctx.data["priority"]
    return Change(event={"from": before, "to": request.priority})


HANDLERS = {
    "submit": _submit,
    "claim_next": _claim_next,
    "assign": _assign,
    "reassign": _reassign,
    "start": _start,
    "request_info": _request_info,
    "respond": _respond,
    "resume": _resume,
    "resolve": _resolve,
    "reject": _reject,
    "withdraw": _withdraw,
    "reopen": _reopen,
    "set_priority": _set_priority,
}


# --- the engine -------------------------------------------------------------------------------


def _db_now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT now()")  # constant for the whole transaction
        return cursor.fetchone()[0]


def check_version(request: ServiceRequest, if_match: int | None) -> None:
    if if_match is not None and if_match != request.version:
        raise AppError(
            "PRECONDITION_FAILED",
            _("Someone else changed this request. Reload it and try again."),
            412,
        )


def perform(
    user: User,
    public_id,
    action: str,
    data: dict | None = None,
    *,
    if_match=None,
    http_request=None,
) -> ServiceRequest:
    """Lock the request, as far as `user` can see it, and apply `action`."""
    with transaction.atomic():
        request = (
            visible_to(user)
            .select_for_update(of=("self",))
            .select_related("category")
            .filter(public_id=public_id)
            .first()
        )
        if request is None:
            raise Http404
        check_version(request, if_match)
        return apply(request, action, user, data or {}, http_request=http_request)


def apply(
    request: ServiceRequest, action: str, user: User, data: dict, *, http_request=None
) -> ServiceRequest:
    """Apply an action to a request the caller has already locked. Call inside a transaction."""
    rule = RULES[action]
    if not actors_of(user, request) & rule.actors:
        raise AppError("NOT_ALLOWED", _("You are not allowed to do this with this request."), 403)
    if request.status not in rule.sources:
        raise AppError(
            "INVALID_TRANSITION", _("This cannot be done while the request is in this state."), 409
        )

    before = request.status
    after = rule.target or before
    ctx = Context(user=user, now=_db_now(), data=data)

    # Leaving AWAITING_CITIZEN ends the pause, whatever comes next. The deadline is recomputed
    # before the handler runs, so a handler that reads it (reject's late-rejection check) and
    # the stored deadline of a closed request both count the pause that just ended.
    if before == Status.AWAITING_CITIZEN and after != Status.AWAITING_CITIZEN:
        SlaPause.objects.filter(request=request, ended_at__isnull=True).update(ended_at=ctx.now)
        request.due_at = compute_due_at(request)

    change = HANDLERS[action](request, ctx)
    request.status = after
    request.version += 1
    request.save()

    request.events.create(
        actor=user,
        actor_role=user.role,
        event_type=action,
        from_status=before,
        to_status=after,
        is_public=rule.public,
        data=change.event,
    )
    audit.record(
        f"request.{action}",
        actor=user,
        target=request,
        request=request,
        data={"from": before, "to": after, **change.event, **change.audit},
        http_request=http_request,
    )
    for recipient, template, kind in change.notices:
        notifications.notify(
            recipient,
            template,
            {"tracking_no": request.tracking_no},
            kind=kind,
            request=request,
            expires_in=STATUS_NOTICE_TTL if kind == Kind.STATUS else None,
        )
    return request
