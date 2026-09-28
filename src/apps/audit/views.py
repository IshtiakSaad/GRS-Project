"""Transparency: who looked at a request (design §7.5, E7.4) and the break-glass report."""

from datetime import timedelta

from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.accounts.permissions import IsAdmin, IsAnyUser
from apps.common.errors import AppError
from apps.common.pagination import KeysetPagination
from apps.common.schema import errors
from apps.directory.models import Department
from apps.service_requests.models import ServiceRequest
from apps.service_requests.transitions import visible_to

from . import access, serializers
from .models import AccessEvent, AccessEventItem, AccessKind


def _context(events) -> dict:
    """Names for a page of events: looked up once, not per row."""
    return {
        "departments": Department.objects.in_bulk({e.actor_department_id for e in events} - {None}),
        "users": User.objects.in_bulk({e.actor_id for e in events}),
        "requests": ServiceRequest.objects.in_bulk({e.request_id for e in events} - {None}),
    }


class AccessLogView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=["transparency"],
        responses={
            200: serializers.AuditorAccessOut(many=True),
            **errors(e403=["NOT_ALLOWED"], e404=["NOT_FOUND"]),
        },
        description="Who opened, changed or downloaded from this request, newest first. The "
        "owner sees the office and role, never a name; administrators also see who and why. "
        "`list_appearances` counts the staff list pages that showed the request.",
    )
    def get(self, request, request_id):
        user = request.user
        if user.role == Role.OFFICER:
            raise AppError("NOT_ALLOWED", _("Only the citizen and auditors see this log."), 403)
        req = visible_to(user).filter(public_id=request_id).first()
        if req is None:
            raise Http404
        access.record(user, req)  # an auditor reading the log is looking at the request too
        events = AccessEvent.objects.filter(request_id=req.pk).exclude(kind=AccessKind.LIST)
        paginator = KeysetPagination()
        page = paginator.paginate_queryset(events, request, view=self)
        out = serializers.AuditorAccessOut if user.role == Role.ADMIN else serializers.AccessOut
        response = paginator.get_paginated_response(
            out(page, many=True, context=_context(page)).data
        )
        response.data["list_appearances"] = AccessEventItem.objects.filter(
            request_id=req.pk
        ).count()
        return response


class BreakGlassReportView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["admin"],
        parameters=[OpenApiParameter("days", int, description="Look-back, 1 to 366. Default 30.")],
        responses={
            200: serializers.BreakGlassReportOut(many=True),
            **errors(e400=["VALIDATION_ERROR"]),
        },
        description="Every time an officer opened a request outside their scope, with the "
        "reason they gave. Reviewed monthly.",
    )
    def get(self, request):
        raw = request.query_params.get("days", "30")
        if not raw.isdigit() or not 1 <= int(raw) <= 366:
            message = _("Choose between 1 and 366 days.")
            raise AppError("VALIDATION_ERROR", message, 400, {"days": [message]})
        since = timezone.now() - timedelta(days=int(raw))
        events = AccessEvent.objects.filter(break_glass_reason__isnull=False, created_at__gte=since)
        paginator = KeysetPagination()
        page = paginator.paginate_queryset(events, request, view=self)
        return paginator.get_paginated_response(
            serializers.BreakGlassReportOut(page, many=True, context=_context(page)).data
        )
