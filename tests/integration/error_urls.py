"""Throwaway views that raise each kind of error, so the envelope can be tested in isolation."""

from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import AppError


class _Payload(serializers.Serializer):
    title = serializers.CharField(max_length=5)


class ValidationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        _Payload(data=request.data).is_valid(raise_exception=True)
        return Response({})


class DomainErrorView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raise AppError("INVALID_TRANSITION", "Cannot resolve a draft.", 409)


class DefaultPermissionView(APIView):
    """Declares no permission, so the project default applies."""

    def get(self, request):
        return Response({"leaked": True})


class CrashView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise RuntimeError("boom")


urlpatterns = [
    path("validation", ValidationView.as_view()),
    path("domain", DomainErrorView.as_view()),
    path("default-permission", DefaultPermissionView.as_view()),
    path("crash", CrashView.as_view()),
]

handler404 = "apps.common.errors.not_found"
handler500 = "apps.common.errors.server_error"
