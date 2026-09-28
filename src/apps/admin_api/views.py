"""Administration endpoints. Every one needs an administrator with a two-step session (IsAdmin
checks `mfa` on the token), and every change is audited in the service layer."""

from datetime import date, timedelta

from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.common import ratelimit
from apps.common.errors import AppError
from apps.common.pagination import KeysetPagination
from apps.common.schema import errors
from apps.directory.models import Category, Department, Holiday, SlaSuspension
from apps.sla.calendar import DHAKA

from . import reviews, serializers, services, stats

INVALID = ["VALIDATION_ERROR"]


def _input(serializer_class, request, *, data=None, partial=False):
    s = serializer_class(data=request.data if data is None else data, partial=partial)
    s.is_valid(raise_exception=True)
    return s.validated_data


class AdminView(APIView):
    permission_classes = [IsAdmin]
    rate_limits = dict.fromkeys(("POST", "PATCH", "DELETE"), ratelimit.ADMIN_WRITE)


# --- departments ------------------------------------------------------------------------------


class DepartmentsView(AdminView):
    @extend_schema(
        tags=["admin"], responses={200: serializers.DepartmentOut(many=True), **errors()}
    )
    def get(self, request):
        rows = Department.objects.order_by("code")
        return Response(serializers.DepartmentOut(rows, many=True).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.DepartmentIn,
        responses={
            201: serializers.DepartmentOut,
            **errors(e400=INVALID, e409=["CODE_IN_USE"]),
        },
    )
    def post(self, request):
        dept = services.create_department(
            request.user, dict(_input(serializers.DepartmentIn, request)), request
        )
        return Response(serializers.DepartmentOut(dept).data, status=status.HTTP_201_CREATED)


class DepartmentView(AdminView):
    @extend_schema(
        tags=["admin"],
        request=serializers.DepartmentPatchIn,
        responses={200: serializers.DepartmentOut, **errors(e400=INVALID, e404=["NOT_FOUND"])},
        description="Deactivating a department withdraws its services from new requests; "
        "requests already filed are still worked.",
    )
    def patch(self, request, code):
        data = _input(serializers.DepartmentPatchIn, request)
        dept = services.update_department(request.user, code, dict(data), request)
        return Response(serializers.DepartmentOut(dept).data)


# --- categories -------------------------------------------------------------------------------


class CategoriesView(AdminView):
    @extend_schema(
        tags=["admin"],
        parameters=[OpenApiParameter("department", str, description="Department code.")],
        responses={200: serializers.CategoryAdminOut(many=True), **errors()},
        description="Every category, active or not.",
    )
    def get(self, request):
        rows = Category.objects.select_related("department").order_by("department__code", "code")
        if request.query_params.get("department"):
            rows = rows.filter(department__code=request.query_params["department"])
        return Response(serializers.CategoryAdminOut(rows, many=True).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.CategoryIn,
        responses={
            201: serializers.CategoryAdminOut,
            **errors(e400=INVALID, e409=["CODE_IN_USE"]),
        },
    )
    def post(self, request):
        data = dict(_input(serializers.CategoryIn, request))
        category = services.create_category(request.user, data, request)
        return Response(serializers.CategoryAdminOut(category).data, status=status.HTTP_201_CREATED)


class CategoryView(AdminView):
    @extend_schema(
        tags=["admin"],
        request=serializers.CategoryPatchIn,
        responses={
            200: serializers.CategoryAdminOut,
            **errors(e400=INVALID, e404=["NOT_FOUND"]),
        },
        description="The department cannot change. A new target recomputes the deadlines of "
        "the category's open requests.",
    )
    def patch(self, request, code):
        data = _input(serializers.CategoryPatchIn, request)
        category = services.update_category(request.user, code, dict(data), request)
        return Response(serializers.CategoryAdminOut(category).data)


# --- holidays and suspensions -----------------------------------------------------------------


class HolidaysView(AdminView):
    @extend_schema(
        tags=["admin"],
        parameters=[OpenApiParameter("year", int)],
        responses={200: serializers.HolidayOut(many=True), **errors(e400=INVALID)},
    )
    def get(self, request):
        rows = Holiday.objects.order_by("date")
        year = request.query_params.get("year")
        if year:
            if not year.isdigit():
                raise AppError(
                    "VALIDATION_ERROR",
                    _("Some fields are invalid."),
                    400,
                    {"year": [_("Enter a year, e.g. 2026.")]},
                )
            rows = rows.filter(date__year=int(year))
        return Response(serializers.HolidayOut(rows, many=True).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.HolidayIn,
        responses={
            201: serializers.HolidayOut,
            **errors(e400=INVALID, e409=["HOLIDAY_EXISTS"]),
        },
        description="Recomputes the deadlines of all open requests (late-announced Eid "
        "dates, sudden government holidays).",
    )
    def post(self, request):
        holiday = services.create_holiday(
            request.user, dict(_input(serializers.HolidayIn, request)), request
        )
        return Response(serializers.HolidayOut(holiday).data, status=status.HTTP_201_CREATED)


class HolidayView(AdminView):
    @extend_schema(tags=["admin"], responses={204: None, **errors(e404=["NOT_FOUND"])})
    def delete(self, request, day):
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise Http404 from exc
        services.delete_holiday(request.user, parsed, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SuspensionsView(AdminView):
    @extend_schema(
        tags=["admin"], responses={200: serializers.SuspensionOut(many=True), **errors()}
    )
    def get(self, request):
        rows = SlaSuspension.objects.select_related("scope_department").order_by("-starts_on")
        return Response(serializers.SuspensionOut(rows, many=True).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.SuspensionIn,
        responses={201: serializers.SuspensionOut, **errors(e400=INVALID)},
        description="Force majeure (internet shutdown, disaster): suspended days do not count "
        "toward deadlines, nationally or for one department.",
    )
    def post(self, request):
        data = dict(_input(serializers.SuspensionIn, request))
        suspension = services.create_suspension(request.user, data, request)
        return Response(serializers.SuspensionOut(suspension).data, status=status.HTTP_201_CREATED)


class SuspensionView(AdminView):
    @extend_schema(tags=["admin"], responses={204: None, **errors(e404=["NOT_FOUND"])})
    def delete(self, request, pk):
        services.delete_suspension(request.user, pk, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- users ------------------------------------------------------------------------------------


class UsersView(AdminView):
    @extend_schema(
        tags=["admin"],
        parameters=[serializers.UserFilterIn],
        responses={200: serializers.UserOut(many=True), **errors(e400=INVALID)},
    )
    def get(self, request):
        wanted = _input(serializers.UserFilterIn, request, data=request.query_params)
        rows = User.objects.select_related("department")
        if "role" in wanted:
            rows = rows.filter(role=wanted["role"])
        if "department" in wanted:
            rows = rows.filter(department__code=wanted["department"])
        if wanted.get("is_active") is not None:
            rows = rows.filter(is_active=wanted["is_active"])
        if "phone" in wanted:
            rows = rows.filter(phone=wanted["phone"])
        paginator = KeysetPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(serializers.UserOut(page, many=True).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.NewOfficerIn,
        responses={201: serializers.UserOut, **errors(e400=INVALID, e409=["PHONE_IN_USE"])},
        description="Creates an officer without a password. A code goes by SMS to the "
        "officer's phone; they set their own password with POST /auth/password/reset/confirm. "
        "Nobody else ever knows it.",
    )
    def post(self, request):
        officer = services.create_officer(
            request.user, _input(serializers.NewOfficerIn, request), request
        )
        return Response(serializers.UserOut(officer).data, status=status.HTTP_201_CREATED)


class UserView(AdminView):
    @extend_schema(
        tags=["admin"], responses={200: serializers.UserOut, **errors(e404=["NOT_FOUND"])}
    )
    def get(self, request, user_id):
        return Response(serializers.UserOut(services.user_by_public_id(user_id)).data)

    @extend_schema(
        tags=["admin"],
        request=serializers.UserPatchIn,
        responses={
            200: serializers.UserOut,
            **errors(e400=INVALID, e404=["NOT_FOUND"], e409=["CANNOT_CHANGE_SELF"]),
        },
        description="Deactivating ends every session and access token of the account at once. "
        "Reassign their open requests afterwards.",
    )
    def patch(self, request, user_id):
        data = _input(serializers.UserPatchIn, request)
        user = services.update_user(request.user, user_id, data, request)
        return Response(serializers.UserOut(user).data)


class UserResetPasswordView(AdminView):
    @extend_schema(
        tags=["admin"],
        request=None,
        responses={202: None, **errors(e403=["NOT_ALLOWED"], e404=["NOT_FOUND"])},
        description="Staff only. The current password stops working and every session ends; a "
        "reset code goes to the staff member's own phone.",
    )
    def post(self, request, user_id):
        services.reset_password(request.user, user_id, request)
        return Response(status=status.HTTP_202_ACCEPTED)


# --- statistics -------------------------------------------------------------------------------


class StatsView(AdminView):
    @extend_schema(
        tags=["admin"],
        parameters=[serializers.StatsIn],
        responses={200: serializers.StatsOut, **errors(e400=INVALID)},
        description="Each primary metric beside the counter-metrics that would reveal it being "
        "gamed, by department, category or officer. Requests submitted in the period "
        "(Asia/Dhaka dates).",
    )
    def get(self, request):
        wanted = _input(serializers.StatsIn, request, data=request.query_params)
        today = timezone.now().astimezone(DHAKA).date()
        last = wanted.get("date_to") or today
        first = wanted.get("date_from") or last - timedelta(days=29)
        if last < first or (last - first).days > 400:
            message = _("Choose a period of at most 400 days, date_from before date_to.")
            raise AppError("VALIDATION_ERROR", message, 400, {"date_from": [message]})
        return Response(serializers.StatsOut(stats.report(wanted["by"], first, last)).data)


# --- review queue -----------------------------------------------------------------------------


class ReviewsView(AdminView):
    @extend_schema(
        tags=["admin"],
        parameters=[serializers.ReviewFilterIn],
        responses={200: serializers.ReviewOut(many=True), **errors(e400=INVALID)},
        description="Closed requests to check after the fact: every late rejection, and a "
        "random share of resolutions. Newest first; filter status=PENDING for the queue.",
    )
    def get(self, request):
        wanted = _input(serializers.ReviewFilterIn, request, data=request.query_params)
        rows = reviews.queue(**wanted)
        paginator = KeysetPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(serializers.ReviewOut(page, many=True).data)


class ReviewDecisionView(AdminView):
    @extend_schema(
        tags=["admin"],
        request=serializers.ReviewDecisionIn,
        responses={
            200: serializers.ReviewOut,
            **errors(
                e400=INVALID,
                e403=["OWN_DECISION"],
                e404=["NOT_FOUND"],
                e409=["ALREADY_REVIEWED", "REQUEST_CHANGED"],
            ),
        },
        description="UPHOLD closes the review. OVERTURN (a note is required) sends the request "
        "back to the queue with a new deadline and tells the citizen.",
    )
    def post(self, request, review_id):
        data = _input(serializers.ReviewDecisionIn, request)
        review = reviews.decide(
            request.user, review_id, data["decision"], data.get("note"), http_request=request
        )
        return Response(serializers.ReviewOut(review).data)
