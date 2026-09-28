"""HTTP for requests. Thin: validate input, call a service, shape the answer for the caller."""

from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.accounts.permissions import IsAnyUser, IsOfficer, IsPublic
from apps.common import idempotency
from apps.common.errors import AppError
from apps.common.pagination import KeysetPagination
from apps.directory.models import Category

from . import serializers, services, transitions
from .models import ServiceRequest, Status

TAG = ["requests"]
QUEUE_PAGE = 20

IF_MATCH = OpenApiParameter(
    "If-Match", str, OpenApiParameter.HEADER, required=True, description='The ETag, e.g. "3".'
)
IDEMPOTENCY_KEY = OpenApiParameter(
    "Idempotency-Key",
    str,
    OpenApiParameter.HEADER,
    description="Required for submit: 8 to 64 letters, digits, - or _. Reuse it on retries.",
)


def _input(serializer_class, request, partial=False):
    s = serializer_class(data=request.data, partial=partial)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _etag(req: ServiceRequest) -> str:
    return f'"{req.version}"'


def _if_match(request) -> int:
    """Required where overwriting someone else's edit is the risk (design §9.3)."""
    raw = request.headers.get("If-Match")
    if raw is None:
        raise AppError(
            "PRECONDITION_REQUIRED", _("Reload the request and send its ETag as If-Match."), 428
        )
    value = raw.strip().removeprefix('"').removesuffix('"')
    if not value.isdigit():
        raise AppError(
            "PRECONDITION_FAILED",
            _("Someone else changed this request. Reload it and try again."),
            412,
        )
    return int(value)


def _with_related(queryset):
    return queryset.select_related("category", "department", "owner", "assigned_officer")


def present(req: ServiceRequest, user) -> dict:
    staff = user.role in (Role.OFFICER, Role.ADMIN)
    serializer = serializers.StaffRequestOut if staff else serializers.RequestOut
    return serializer(req).data


def _detail(req: ServiceRequest, user, code=status.HTTP_200_OK) -> Response:
    return Response(present(req, user), status=code, headers={"ETag": _etag(req)})


def _reload(req: ServiceRequest) -> ServiceRequest:
    return _with_related(ServiceRequest.objects).get(pk=req.pk)


# --- directory --------------------------------------------------------------------------------


class CategoriesView(APIView):
    """The services a citizen can request. Public: the list is shown before login."""

    authentication_classes: list = []
    permission_classes = [IsPublic]

    @extend_schema(tags=TAG, responses={200: serializers.CategoryOut(many=True)})
    def get(self, request):
        rows = (
            Category.objects.filter(is_active=True, department__is_active=True)
            .select_related("department")
            .order_by("department__code", "code")
        )
        return Response(serializers.CategoryOut(rows, many=True).data)


# --- requests ---------------------------------------------------------------------------------


class RequestsView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("status", str, enum=Status.values)],
        responses={200: serializers.RequestRowOut(many=True)},
        description="Citizens see their own requests; staff see short rows of the requests in "
        "their scope and open one to see details.",
    )
    def get(self, request):
        rows = transitions.visible_to(request.user).select_related("category", "owner")
        wanted = request.query_params.get("status")
        if wanted:
            if wanted not in Status.values:
                raise AppError("VALIDATION_ERROR", _("Unknown status."), 400)
            rows = rows.filter(status=wanted)
        paginator = KeysetPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        staff = request.user.role != Role.CITIZEN
        row = serializers.StaffRowOut if staff else serializers.RequestRowOut
        return paginator.get_paginated_response(row(page, many=True).data)

    @extend_schema(tags=TAG, request=serializers.DraftIn, responses={201: serializers.RequestOut})
    def post(self, request):
        if request.user.role != Role.CITIZEN:
            raise PermissionDenied  # assisted submission by officers is a later feature
        draft = services.create_draft(request.user, _input(serializers.DraftIn, request))
        return _detail(_reload(draft), request.user, status.HTTP_201_CREATED)


class RequestView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=TAG, responses={200: serializers.StaffRequestOut, 304: None})
    def get(self, request, request_id):
        req = _with_related(transitions.visible_to(request.user)).filter(public_id=request_id)
        req = req.first()
        if req is None:
            raise Http404
        if request.headers.get("If-None-Match") == _etag(req):
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={"ETag": _etag(req)})
        return _detail(req, request.user)

    @extend_schema(
        tags=TAG,
        request=serializers.DraftIn,
        parameters=[IF_MATCH],
        responses={200: serializers.RequestOut},
        description="Edit a draft. Send only the fields that change.",
    )
    def patch(self, request, request_id):
        data = _input(serializers.DraftIn, request, partial=True)
        draft = services.edit_draft(request.user, request_id, data, _if_match(request))
        return _detail(_reload(draft), request.user)

    @extend_schema(tags=TAG, parameters=[IF_MATCH], responses={204: None})
    def delete(self, request, request_id):
        services.discard_draft(request.user, request_id, _if_match(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RequestActionView(APIView):
    """Every state change after the draft, by name (design §5.2)."""

    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        parameters=[IDEMPOTENCY_KEY],
        request=serializers.SubmitIn,
        responses={200: serializers.StaffRequestOut},
        description="Actions: " + ", ".join(serializers.ACTION_INPUTS) + ". The body depends "
        "on the action. `submit` needs an Idempotency-Key header.",
    )
    def post(self, request, request_id, action):
        if action not in serializers.ACTION_INPUTS:
            raise Http404
        data = _input(serializers.ACTION_INPUTS[action], request)

        def run():
            req = transitions.perform(request.user, request_id, action, data, http_request=request)
            return status.HTTP_200_OK, present(_reload(req), request.user)

        if action != "submit":
            code, body = run()
            return Response(body, status=code, headers={"ETag": f'"{body["version"]}"'})

        key = idempotency.read_key(request)
        fp = idempotency.fingerprint(request.method, request.path, data)
        code, body, replayed = idempotency.once(request.user, key, fp, run)
        headers = {"ETag": f'"{body["version"]}"'}
        if replayed:
            headers["Idempotent-Replayed"] = "true"
        return Response(body, status=code, headers=headers)


class RequestPriorityView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        request=serializers.PriorityIn,
        parameters=[IF_MATCH],
        responses={200: serializers.StaffRequestOut},
    )
    def patch(self, request, request_id):
        data = _input(serializers.PriorityIn, request)
        req = transitions.perform(
            request.user,
            request_id,
            "set_priority",
            data,
            if_match=_if_match(request),
            http_request=request,
        )
        return _detail(_reload(req), request.user)


class ByTrackingView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        responses={200: serializers.StaffRequestOut},
        description="Accepts Bangla digits, spaces and missing dashes: ২৬ ০০০৪২১৩ ৭ works.",
    )
    def get(self, request, number):
        req = services.by_tracking_no(request.user, number)
        return _detail(_reload(req), request.user)


class TimelineView(APIView):
    permission_classes = [IsAnyUser]
    pagination_class = None

    @extend_schema(tags=TAG, responses={200: serializers.EventOut(many=True)})
    def get(self, request, request_id):
        req = transitions.visible_to(request.user).filter(public_id=request_id).first()
        if req is None:
            raise Http404
        events = req.events.select_related("actor").order_by("created_at", "id")
        if request.user.role == Role.CITIZEN:
            return Response(serializers.EventOut(events.filter(is_public=True), many=True).data)
        return Response(serializers.StaffEventOut(events, many=True).data)


# --- the queue --------------------------------------------------------------------------------


class QueueView(APIView):
    permission_classes = [IsOfficer]

    @extend_schema(tags=["queue"], responses={200: serializers.QueueOut})
    def get(self, request):
        waiting = services.queue(request.user)
        rows = waiting.select_related("category", "owner")[:QUEUE_PAGE]
        return Response(
            {
                "waiting": waiting.count(),
                "requests": serializers.StaffRowOut(rows, many=True).data,
            }
        )


class ClaimNextView(APIView):
    permission_classes = [IsOfficer]

    @extend_schema(
        tags=["queue"],
        request=None,
        responses={200: serializers.StaffRequestOut, 204: None},
        description="Take the most urgent waiting request of your department. 204 when the "
        "queue is empty.",
    )
    def post(self, request):
        req = services.claim_next(request.user, http_request=request)
        if req is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return _detail(_reload(req), request.user)
