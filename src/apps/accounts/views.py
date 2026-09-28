"""HTTP for identity. Thin: validate input, call a service, shape the answer."""

from django.conf import settings
from django.http import Http404
from django.utils import translation
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import AppError
from apps.common.phone import normalise_phone
from apps.notifications.models import DemoSms

from . import otp, serializers, services, sessions
from .models import RefreshSession
from .permissions import IsAnyUser, IsPublic, IsStaff

TAG = ["auth"]


def _input(serializer_class, request):
    s = serializer_class(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _ua(request) -> str:
    return request.headers.get("User-Agent", "")


def _accepted() -> Response:
    return Response(
        {
            "detail": _("If the number can receive it, a code has been sent by SMS."),
            "resend_after": int(otp.COOLDOWN.total_seconds()),
        },
        status=status.HTTP_202_ACCEPTED,
    )


class PublicView(APIView):
    """No login; a stray Authorization header is ignored rather than rejected."""

    authentication_classes: list = []
    permission_classes = [IsPublic]


# --- registration and phone verification ------------------------------------------------------


class RegisterView(PublicView):
    @extend_schema(
        tags=TAG, request=serializers.RegisterIn, responses={202: serializers.AcceptedOut}
    )
    def post(self, request):
        data = _input(serializers.RegisterIn, request)
        language = data.get("preferred_language") or translation.get_language()[:2]
        services.register(data["phone"], data["password"], data["full_name"], language)
        return _accepted()


class VerifyPhoneView(PublicView):
    @extend_schema(tags=TAG, request=serializers.PhoneCodeIn, responses={204: None})
    def post(self, request):
        data = _input(serializers.PhoneCodeIn, request)
        services.verify_phone(data["phone"], data["code"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResendCodeView(PublicView):
    @extend_schema(tags=TAG, request=serializers.PhoneIn, responses={202: serializers.AcceptedOut})
    def post(self, request):
        services.resend_phone_code(_input(serializers.PhoneIn, request)["phone"])
        return _accepted()


# --- login and sessions -----------------------------------------------------------------------


class LoginView(PublicView):
    @extend_schema(tags=TAG, request=serializers.LoginIn, responses={200: serializers.LoginOut})
    def post(self, request):
        data = _input(serializers.LoginIn, request)
        result = services.login(
            data["phone"],
            data["password"],
            device_token=data.get("device_token"),
            trust_mode=data["trust_mode"],
            user_agent=_ua(request),
            http_request=request,
        )
        return Response(result)


class SecondFactorView(PublicView):
    @extend_schema(
        tags=TAG,
        request=serializers.SecondFactorIn,
        responses={200: serializers.TokensOut},
        description="Second step of an administrator's (or opted-in officer's) login.",
    )
    def post(self, request):
        data = _input(serializers.SecondFactorIn, request)
        return Response(
            services.verify_second_factor(
                data["mfa_token"], data["code"], user_agent=_ua(request), http_request=request
            )
        )


class RecoveryCodeView(PublicView):
    @extend_schema(
        tags=TAG, request=serializers.SecondFactorIn, responses={200: serializers.TokensOut}
    )
    def post(self, request):
        data = _input(serializers.SecondFactorIn, request)
        return Response(
            services.use_recovery_code(
                data["mfa_token"], data["code"], user_agent=_ua(request), http_request=request
            )
        )


class RefreshView(PublicView):
    @extend_schema(tags=TAG, request=serializers.RefreshIn, responses={200: serializers.TokensOut})
    def post(self, request):
        raw = _input(serializers.RefreshIn, request)["refresh"]
        try:
            issued = sessions.rotate(raw, http_request=request)
        except sessions.InvalidRefresh as exc:
            raise AppError(
                "SESSION_EXPIRED", _("Your session has expired. Please log in again."), 401
            ) from exc
        return Response(issued.as_dict())


class LogoutView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=TAG, request=None, responses={204: None})
    def post(self, request):
        services.logout(request.auth["sid"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- password ---------------------------------------------------------------------------------


class PasswordResetRequestView(PublicView):
    @extend_schema(tags=TAG, request=serializers.PhoneIn, responses={202: serializers.AcceptedOut})
    def post(self, request):
        services.request_password_reset(_input(serializers.PhoneIn, request)["phone"])
        return _accepted()


class PasswordResetConfirmView(PublicView):
    @extend_schema(tags=TAG, request=serializers.ResetConfirmIn, responses={204: None})
    def post(self, request):
        data = _input(serializers.ResetConfirmIn, request)
        services.confirm_password_reset(
            data["phone"], data["code"], data["new_password"], http_request=request
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- two-step login enrolment (staff) ----------------------------------------------------------


class TotpSetupView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(tags=TAG, request=None, responses={200: serializers.TotpSetupOut})
    def post(self, request):
        return Response(services.begin_totp_setup(request.user))


class TotpConfirmView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(
        tags=TAG, request=serializers.TotpConfirmIn, responses={200: serializers.TotpConfirmOut}
    )
    def post(self, request):
        data = _input(serializers.TotpConfirmIn, request)
        return Response(
            services.confirm_totp_setup(
                request.user,
                data["current_password"],
                data["code"],
                user_agent=_ua(request),
                http_request=request,
            )
        )


# --- email ------------------------------------------------------------------------------------


class EmailVerifyView(PublicView):
    @extend_schema(tags=TAG, request=serializers.EmailTokenIn, responses={204: None})
    def post(self, request):
        services.verify_email(_input(serializers.EmailTokenIn, request)["token"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- the signed-in user -----------------------------------------------------------------------


class MeView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=["me"], responses={200: serializers.MeOut})
    def get(self, request):
        return Response(serializers.MeOut(request.user).data)

    @extend_schema(tags=["me"], request=serializers.MeIn, responses={200: serializers.MeOut})
    def patch(self, request):
        s = serializers.MeIn(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        user = request.user
        data = s.validated_data
        changed = [f for f in ("full_name", "preferred_language") if f in data]
        for field in changed:
            setattr(user, field, data[field])
        if changed:
            user.save(update_fields=changed)
        if "email" in data:
            services.set_email(user, data["email"])
        return Response(serializers.MeOut(user).data)


class MyPasswordView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=["me"], request=serializers.ChangePasswordIn, responses={200: serializers.TokensOut}
    )
    def post(self, request):
        data = _input(serializers.ChangePasswordIn, request)
        return Response(
            services.change_password(
                request.user,
                data["current_password"],
                data["new_password"],
                family_id=request.auth["sid"],
                user_agent=_ua(request),
                http_request=request,
            )
        )


class MySessionsView(APIView):
    permission_classes = [IsAnyUser]
    pagination_class = None

    @extend_schema(tags=["me"], responses={200: serializers.SessionOut(many=True)})
    def get(self, request):
        rows = sessions.active_sessions(request.user)
        context = {"sid": request.auth["sid"]}
        return Response(serializers.SessionOut(rows, many=True, context=context).data)


class MySessionView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=["me"], responses={204: None})
    def delete(self, request, session_id):
        if not RefreshSession.objects.filter(
            user=request.user, family_id=session_id, revoked_at__isnull=True
        ).exists():
            raise Http404
        sessions.revoke_family(session_id, "user_revoked")
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- demo -------------------------------------------------------------------------------------


class DemoSmsView(PublicView):
    """What the fake SMS provider "sent" to a demo number. Absent unless DEMO_MODE is on."""

    @extend_schema(tags=["demo"], responses={200: serializers.DemoSmsOut(many=True)})
    def get(self, request, phone):
        number = normalise_phone(phone)
        if not settings.DEMO_MODE or number is None:
            raise Http404
        rows = DemoSms.objects.filter(phone=number).order_by("-created_at")[:10]
        return Response(serializers.DemoSmsOut(rows, many=True).data)
