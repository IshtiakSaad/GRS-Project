"""HTTP for identity. Thin: validate input, call a service, shape the answer."""

from django.conf import settings
from django.http import Http404
from django.utils import translation
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import ratelimit
from apps.common.errors import AppError
from apps.common.phone import normalise_phone
from apps.common.schema import errors
from apps.notifications.models import DemoSms

from . import otp, serializers, services, sessions
from .models import RefreshSession
from .permissions import IsAnyUser, IsPublic, IsStaff

TAG = ["auth"]
INVALID_INPUT = errors(authenticated=False, e400=["VALIDATION_ERROR"])
DELAYED = ["LOGIN_DELAYED"]
SECOND_FACTOR_ERRORS = errors(
    authenticated=False,
    e400=["VALIDATION_ERROR", "INVALID_CODE"],
    e401=["MFA_TOKEN_INVALID"],
    e429=DELAYED,
)


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
    rate_limits = {"POST": ratelimit.REGISTER}

    @extend_schema(
        tags=TAG,
        request=serializers.RegisterIn,
        responses={202: serializers.AcceptedOut, **INVALID_INPUT},
        description="The answer is the same whether or not the number already has an account.",
    )
    def post(self, request):
        data = _input(serializers.RegisterIn, request)
        language = data.get("preferred_language") or translation.get_language()[:2]
        services.register(data["phone"], data["password"], data["full_name"], language)
        return _accepted()


class VerifyPhoneView(PublicView):
    rate_limits = {"POST": ratelimit.CODE_CHECK}

    @extend_schema(
        tags=TAG,
        request=serializers.PhoneCodeIn,
        responses={
            204: None,
            **errors(authenticated=False, e400=["VALIDATION_ERROR", "INVALID_CODE"]),
        },
    )
    def post(self, request):
        data = _input(serializers.PhoneCodeIn, request)
        services.verify_phone(data["phone"], data["code"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResendCodeView(PublicView):
    rate_limits = {"POST": ratelimit.CODE_SEND}

    @extend_schema(
        tags=TAG,
        request=serializers.PhoneIn,
        responses={202: serializers.AcceptedOut, **INVALID_INPUT},
    )
    def post(self, request):
        services.resend_phone_code(_input(serializers.PhoneIn, request)["phone"])
        return _accepted()


# --- login and sessions -----------------------------------------------------------------------


class LoginView(PublicView):
    rate_limits = {"POST": ratelimit.LOGIN}

    @extend_schema(
        tags=TAG,
        request=serializers.LoginIn,
        responses={
            200: serializers.LoginOut,
            **errors(
                authenticated=False,
                e400=["VALIDATION_ERROR"],
                e401=["INVALID_CREDENTIALS"],
                e429=DELAYED,
            ),
        },
        description="Returns tokens, or, for accounts with two-step login, `mfa_token` to "
        "exchange at /auth/2fa/verify. 429 carries Retry-After.",
        examples=[
            OpenApiExample(
                "A demo citizen",
                value={"phone": "+8801000000102", "password": "demo-password-2026"},
                request_only=True,
            ),
            OpenApiExample(
                "Logged in",
                value={
                    "device_token": "Z1Vb…",
                    "mfa_required": False,
                    "access": "eyJhbGciOiJIUzI1NiIsImtpZCI6ImsxIn0…",
                    "refresh": "nq8Xw…",
                    "session_id": "0199a3c1-5b7e-7c41-9d2e-3f6a8b1c2d4e",
                    "token_type": "Bearer",
                    "expires_in": 600,
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                "Two-step login needed (administrators)",
                value={"device_token": "Z1Vb…", "mfa_required": True, "mfa_token": "eyJ0…"},
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
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
        responses={200: serializers.TokensOut, **SECOND_FACTOR_ERRORS},
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
        tags=TAG,
        request=serializers.SecondFactorIn,
        responses={200: serializers.TokensOut, **SECOND_FACTOR_ERRORS},
        description="Second step with a one-time recovery code instead of the authenticator.",
    )
    def post(self, request):
        data = _input(serializers.SecondFactorIn, request)
        return Response(
            services.use_recovery_code(
                data["mfa_token"], data["code"], user_agent=_ua(request), http_request=request
            )
        )


class RefreshView(PublicView):
    @extend_schema(
        tags=TAG,
        request=serializers.RefreshIn,
        responses={
            200: serializers.TokensOut,
            **errors(authenticated=False, e400=["VALIDATION_ERROR"], e401=["SESSION_EXPIRED"]),
        },
        description="Rotates the refresh token. A retry within 60 s gets the same new token.",
    )
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

    @extend_schema(tags=TAG, request=None, responses={204: None, **errors()})
    def post(self, request):
        services.logout(request.auth["sid"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- password ---------------------------------------------------------------------------------


class PasswordResetRequestView(PublicView):
    rate_limits = {"POST": ratelimit.CODE_SEND}

    @extend_schema(
        tags=TAG,
        request=serializers.PhoneIn,
        responses={202: serializers.AcceptedOut, **INVALID_INPUT},
        description="Same answer for every number. Numbers unused for 180 days get no code.",
    )
    def post(self, request):
        services.request_password_reset(_input(serializers.PhoneIn, request)["phone"])
        return _accepted()


class PasswordResetConfirmView(PublicView):
    rate_limits = {"POST": ratelimit.CODE_CHECK}

    @extend_schema(
        tags=TAG,
        request=serializers.ResetConfirmIn,
        responses={
            204: None,
            **errors(authenticated=False, e400=["VALIDATION_ERROR", "INVALID_CODE"]),
        },
    )
    def post(self, request):
        data = _input(serializers.ResetConfirmIn, request)
        services.confirm_password_reset(
            data["phone"], data["code"], data["new_password"], http_request=request
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- two-step login enrolment (staff) ----------------------------------------------------------


class TotpSetupView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(
        tags=TAG,
        request=None,
        responses={200: serializers.TotpSetupOut, **errors(e409=["TOTP_ALREADY_ENABLED"])},
    )
    def post(self, request):
        return Response(services.begin_totp_setup(request.user))


class TotpConfirmView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(
        tags=TAG,
        request=serializers.TotpConfirmIn,
        responses={
            200: serializers.TotpConfirmOut,
            **errors(
                e400=["VALIDATION_ERROR", "INVALID_CREDENTIALS", "INVALID_CODE"],
                e409=["TOTP_ALREADY_ENABLED"],
                e429=DELAYED,
            ),
        },
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
    @extend_schema(
        tags=TAG,
        request=serializers.EmailTokenIn,
        responses={
            204: None,
            **errors(authenticated=False, e400=["VALIDATION_ERROR", "INVALID_CODE"]),
        },
    )
    def post(self, request):
        services.verify_email(_input(serializers.EmailTokenIn, request)["token"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- the signed-in user -----------------------------------------------------------------------


class MeView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=["me"], responses={200: serializers.MeOut, **errors()})
    def get(self, request):
        return Response(serializers.MeOut(request.user).data)

    @extend_schema(
        tags=["me"],
        request=serializers.MeIn,
        responses={
            200: serializers.MeOut,
            **errors(e400=["VALIDATION_ERROR"], e409=["EMAIL_IN_USE"]),
        },
        description="A new email is unverified until the emailed link is used.",
    )
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
        tags=["me"],
        request=serializers.ChangePasswordIn,
        responses={
            200: serializers.TokensOut,
            **errors(e400=["VALIDATION_ERROR", "INVALID_CREDENTIALS"], e429=DELAYED),
        },
        description="Ends every session and returns new tokens for this one.",
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

    @extend_schema(tags=["me"], responses={200: serializers.SessionOut(many=True), **errors()})
    def get(self, request):
        rows = sessions.active_sessions(request.user)
        context = {"sid": request.auth["sid"]}
        return Response(serializers.SessionOut(rows, many=True, context=context).data)


class MySessionView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(tags=["me"], responses={204: None, **errors(e404=["NOT_FOUND"])})
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

    @extend_schema(
        tags=["demo"],
        responses={
            200: serializers.DemoSmsOut(many=True),
            **errors(authenticated=False, e404=["NOT_FOUND"]),
        },
        description="Demo only: the last 10 messages the fake SMS provider stored for a "
        "+880 10… number. Not found outside demo mode.",
    )
    def get(self, request, phone):
        number = normalise_phone(phone)
        if not settings.DEMO_MODE or number is None:
            raise Http404
        rows = DemoSms.objects.filter(phone=number).order_by("-created_at")[:10]
        return Response(serializers.DemoSmsOut(rows, many=True).data)
